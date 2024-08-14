#!/usr/bin/env python3
from typing import List, Dict, Any, Callable, Mapping
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.layout.containers import Window, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style
from prompt_toolkit.styles.named_colors import NAMED_COLORS
from datetime import datetime, timedelta, date
from prompt_toolkit.widgets import (
    TextArea,
    SearchToolbar,
    MenuContainer,
    MenuItem,
)
from prompt_toolkit.key_binding.bindings.focus import (
    focus_next,
    focus_previous,
)
import string
import shutil
import threading
import traceback
import sys
from ZODB import DB, FileStorage
from persistent import Persistent
import transaction
import os
import time

import textwrap
import shutil
import re

# Non-printing character
NON_PRINTING_CHAR = '\u200B'
# Placeholder for spaces within special tokens
PLACEHOLDER = '\u00A0'
# Placeholder for hyphens to prevent word breaks
NON_BREAKING_HYPHEN = '\u2011'

def wrap(text: str, indent: int = 3, width: int = shutil.get_terminal_size()[0] - 3):
    # Preprocess to replace spaces within specific "@\S" patterns with PLACEHOLDER
    text = preprocess_text(text)

    # Split text into paragraphs
    paragraphs = text.split('\n')

    # Wrap each paragraph
    wrapped_paragraphs = []
    for para in paragraphs:
        leading_whitespace = re.match(r'^\s*', para).group()
        initial_indent = leading_whitespace

        # Determine subsequent_indent based on the first non-whitespace character
        stripped_para = para.lstrip()
        if stripped_para.startswith(('+', '-', '*', '%', '!', '~')):
            subsequent_indent = initial_indent + ' ' * 2
        elif stripped_para.startswith(('@', '&')):
            subsequent_indent = initial_indent + ' ' * 3
        elif stripped_para and stripped_para[0].isdigit():
            subsequent_indent = initial_indent + ' ' * 3
        else:
            subsequent_indent = initial_indent + ' ' * indent

        wrapped = textwrap.fill(
            para,
            initial_indent='',
            subsequent_indent=subsequent_indent,
            width=width)
        wrapped_paragraphs.append(wrapped)

    # Join paragraphs with newline followed by non-printing character
    wrapped_text = ('\n' + NON_PRINTING_CHAR).join(wrapped_paragraphs)

    # Postprocess to replace PLACEHOLDER and NON_BREAKING_HYPHEN back with spaces and hyphens
    wrapped_text = postprocess_text(wrapped_text)

    return wrapped_text

def preprocess_text(text):
    # Regex to find "@\S" patterns and replace spaces within the pattern with PLACEHOLDER
    text = re.sub(r'(@\S+\s\S+)', lambda m: m.group(0).replace(' ', PLACEHOLDER), text)
    # Replace hyphens within words with NON_BREAKING_HYPHEN
    text = re.sub(r'(\S)-(\S)', lambda m: m.group(1) + NON_BREAKING_HYPHEN + m.group(2), text)
    return text

def postprocess_text(text):
    text = text.replace(PLACEHOLDER, ' ')
    text = text.replace(NON_BREAKING_HYPHEN, '-')
    return text

def unwrap(wrapped_text):
    # Split wrapped text into paragraphs
    paragraphs = wrapped_text.split('\n' + NON_PRINTING_CHAR)

    # Replace newlines followed by spaces in each paragraph with a single space
    unwrapped_paragraphs = []
    for para in paragraphs:
        unwrapped = re.sub(r'\n\s*', ' ', para)
        unwrapped_paragraphs.append(unwrapped)

    # Join paragraphs with original newlines
    unwrapped_text = '\n'.join(unwrapped_paragraphs)

    return unwrapped_text

def sort_key(tracker):
    # Sorting by None first (using doc_id as secondary sorting)
    if tracker.next_expected_completion is None:
        return (0, tracker.doc_id)
    # Sorting by datetime for non-None values
    else:
        return (1, tracker.next_expected_completion)

# Tracker
class Tracker(Persistent):
    max_history = 10

    @classmethod
    def format_dt(cls, dt: Any) -> str:
        if not isinstance(dt, datetime):
            return ""
        return dt.strftime("%Y-%m-%d %H:%M")

    @classmethod
    def td2seconds(cls, td: timedelta) -> str:
        if not isinstance(td, timedelta):
            return ""
        return f"{round(td.total_seconds())}"

    @classmethod
    def format_td(cls, td: timedelta):
        if not isinstance(td, timedelta):
            return None
        sign = '' if td.total_seconds() >= 0 else '-'
        total_seconds = abs(int(td.total_seconds()))
        if total_seconds == 0:
            return ' 0 minutes '
        total_seconds = abs(total_seconds)
        try:
            until = []
            days = hours = minutes = 0
            if total_seconds:
                minutes = total_seconds // 60
                if minutes >= 60:
                    hours = minutes // 60
                    minutes = minutes % 60
                if hours >= 24:
                    days = hours // 24
                    hours = hours % 24
            if days:
                until.append(f'{days} days')
            if hours:
                until.append(f'{hours} hours')
            if minutes:
                until.append(f'{minutes} minutes')
            if not until:
                until.append('0 minutes')
            ret = sign + ' '.join(until)
            return ret
        except Exception as e:
            print(f'{td}: {e}')
            return ''


    @classmethod
    def parse_dt(cls, dt: str = "") -> datetime:
        if isinstance(dt, datetime):
            return dt
        elif dt.strip() == "now":
            dt = datetime.now()
            return dt
        elif isinstance(dt, str) and dt:
            pi = parserinfo(
                dayfirst=False,
                yearfirst=True)
            try:
                dt = parse(dt, parserinfo=pi)
                return dt
            except Exception as e:
                print(f"Error parsing datetime: {dt}\ne {repr(e)}\n{traceback.format_exc()}", file=sys.stderr, flush=True)
                return None
        else:
            return None

    def __init__(self, name: str, doc_id: int) -> None:
        self.doc_id = int(doc_id)
        self.name = name
        self.history = []


    @property
    def info(self):
        # Lazy initialization with re-computation logic
        if not hasattr(self, '_info') or self._info is None:
            self._info = self.compute_info()
        return self._info

    # @info.setter
    # def info(self, value):
    #     # This setter could be used if you want to manually set it
    #     self._info = value
    #     self._p_changed = True  # Mark the object as changed in ZODB

    def compute_info(self):
        # Example computation based on history, returning a dict
        result = {}
        if not self.history:
            result = dict(last_completion=None, num_completions=0, num_intervals=0, average_interval=timedelta(minutes=0), last_interval=timedelta(minutes=0), change=timedelta(minutes=0), next_expected_completion=None)
        else:
            result['last_completion'] = self.history[-1] if len(self.history) > 0 else None
            result['num_completions'] = len(self.history)
            if result['num_completions'] > 1:
                intervals = [self.history[i+1] - self.history[i] for i in range(len(self.history) - 1)]
                result['num_intervals'] = len(intervals)
                result['average_interval'] = sum(intervals, timedelta()) / result['num_intervals']
                result['last_interval'] = intervals[-1]
                result['change'] = result['last_interval'] - result['average_interval'] if result['last_interval'] >= result['average_interval'] else - (result['average_interval'] - result['last_interval'])
                result['next_expected_completion'] = result['last_completion'] + result['average_interval']
            else:
                intervals = []
                result['change'] = result['average_interval'] = result['last_interval'] = timedelta(minutes=0)
                result['next_expected_completion'] = None
            result['num_intervals'] = len(intervals)
        self._p_changed = True
        # print(f"returning {result = }")
        return result

    # XXX: Just for reference
    def add_to_history(self, new_event):
        self.history.append(new_event)
        self.invalidate_info()
        self._p_changed = True  # Mark object as changed in ZODB

    def invalidate_info(self):
        # Invalidate the cached dict so it will be recomputed on next access
        if hasattr(self, '_info'):
            delattr(self, '_info')


    def record_completion(self, completion_dt: datetime):
        ok, msg = True, ""
        # needs_sorting = False
        # if self.history and self.history[-1] >= completion_dt:
        #     print(f"""\
        # The new completion datetime
        #     {completion_dt}
        # should be later than the previous completion datetime
        #     {self.history[-1]}
        # but is earlier.""")
        #     res = input("Is this what you wanted? (y/N): ").strip()
        #     if res.lower() not in ['y', 'yes']:
        #         return False, "aborted"
        #     needs_sorting = True
        self.history.append(completion_dt)
        # if needs_sorting:
        self.history.sort()
        if len(self.history) > Tracker.max_history:
            self.history = self.history[-Tracker.max_history:]

        # Notify ZODB that this object has changed
        self.invalidate_info()
        self._p_changed = True

        # print(msg)
        return True, f"recorded completion for {completion_dt}"

    def edit_history(self):
        if not self.history:
            print("No history to edit.")
            return

        # Display current history
        for i, dt in enumerate(self.history):
            print(f"{i + 1}. {self.format_dt(dt)}")

        # Choose an entry to edit
        try:
            choice = int(input("Enter the number of the history entry to edit (or 0 to cancel): ").strip())
            if choice == 0:
                return
            if choice < 1 or choice > len(self.history):
                print("Invalid choice.")
                return
            selected_dt = self.history[choice - 1]
            print(f"Selected date: {self.format_dt(selected_dt)}")

            # Choose what to do with the selected entry
            action = input("Do you want to (d)elete or (r)eplace this entry? ").strip().lower()

            if action == 'd':
                self.history.pop(choice - 1)
                print("Entry deleted.")
            elif action == 'r':
                new_dt_str = input("Enter the new datetime to replace it with: ").strip()
                new_dt = self.parse_dt(new_dt_str)
                if new_dt:
                    self.history[choice - 1] = new_dt
                    print("Entry replaced.")
                else:
                    print("Invalid datetime format.")
            else:
                print("Invalid action.")

            # Sort and truncate history if necessary
            self.history.sort()
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]

            # Notify ZODB that this object has changed
            self.update_tracker_info()
            self._p_changed = True

        except ValueError:
            print("Invalid input. Please enter a number.")

    def get_tracker_info(self):
        if not hasattr(self, '_info') or self._info is None:
            self._info = self.compute_info()
        # insert a placeholder to prevent date and time from being split across multiple lines when wrapping
        format_str = f"%Y-%m-%d{PLACEHOLDER}%H:%M"
        wrapped_history = wrap(', '.join(x.strftime(format_str) for x in self.history))
        return f"""\
 #{self.doc_id} {self.name}
    completions ({self._info['num_completions']}):
        last: {Tracker.format_dt(self._info['last_completion'])}
        next: {Tracker.format_dt(self._info['next_expected_completion'])}
    intervals ({self._info['num_intervals']}):
        average: {Tracker.format_td(self._info['average_interval'])}
        last: {Tracker.format_td(self._info['last_interval'])}
        change: {Tracker.format_td(self._info['change'])}
    history:
        {wrapped_history}
    """

class TrackerManager:
    labels = "abcdefghijklmnopqrstuvwxyz"

    def __init__(self, db_path=None) -> None:
        if db_path is None:
            db_path = os.path.join(os.getcwd(), "tracker.fs")
        self.db_path = db_path
        self.trackers = {}
        self.label_to_id = {}
        self.active_page = 0
        self.storage = FileStorage.FileStorage(self.db_path)
        self.db = DB(self.storage)
        self.connection = self.db.open()
        self.root = self.connection.root()
        print(f"opened tracker manager using data from\n  {self.db_path}")
        self.load_data()

    def add_tracker(self, name: str) -> None:
        doc_id = self.root['next_id']
        tracker = Tracker(name, doc_id)
        self.trackers[doc_id] = tracker
        self.root['next_id'] += 1  # Increment the ID counter
        self.save_data()
        print(f"Tracker '{name}' added with ID {doc_id}")

    def record_completion(self, doc_id: int, dt: datetime):
        # dt will be a datetime
        ok, msg = self.trackers[doc_id].record_completion(dt)
        if not ok:
            print(msg)
            return

        self.save_data()
        print(f"""\
    {doc_id}: Recorded {dt.strftime('%Y-%m-%d %H:%M')} as a completion:\n    {self.trackers[doc_id].get_tracker_data()}""")

    def get_tracker_data(self, doc_id: int = None):
        if doc_id is None:
            print("data for all trackers:")
            for k, v in self.trackers.items():
                print(f"   {k:2> }. {v.get_tracker_data()}")
        elif doc_id in self.trackers:
            print(f"data for tracker {doc_id}:")
            print(f"   {doc_id:2> }. {self.trackers[doc_id].get_tracker_data()}")

    def sort_key(self, tracker):
        next_dt = tracker._info.get('next_expected_completion', None) if hasattr(tracker, '_info') else None
        if next_dt is None:
            return (0, tracker.doc_id)
        else:
            return (1, next_dt)

    def get_sorted_trackers(self):
        # Extract the list of trackers
        trackers = [v for k, v in self.trackers.items()]
        # Sort the trackers
        return sorted(trackers, key=self.sort_key)

    def list_trackers(self):
        num_pages = (len(self.trackers) + 25) // 26
        page_banner = f" (page {self.active_page + 1}/{num_pages})"
        banner = f" Tracker List{page_banner}\n"
        rows = []
        count = 0
        start_index = self.active_page * 26
        end_index = start_index + 26
        sorted_trackers = self.get_sorted_trackers()
        for tracker in sorted_trackers[start_index:end_index]:
            next_dt = tracker._info.get('next_expected_completion', None) if hasattr(tracker, '_info') else None
            next = next_dt.strftime("%a %b %-d") if next_dt else center_text("~", 10)
            label = TrackerManager.labels[count]
            self.label_to_id[(self.active_page, label)] = tracker.doc_id
            count += 1
            rows.append(f" {label}   {next:<10} {tracker.name}")
        return banner +"\n".join(rows)

    def set_active_page(self, page_num):
        if 0 <= page_num < (len(self.trackers) + 25) // 26:
            self.active_page = page_num
        else:
            print("Invalid page number.")

    def next_page(self):
        self.set_active_page(self.active_page + 1)

    def previous_page(self):
        self.set_active_page(self.active_page - 1)

    def get_tracker_from_label(self, label: str):
        pagelabel = (self.active_page, label)
        if pagelabel not in self.label_to_id:
            return None
        return self.trackers[self.label_to_id[pagelabel]]

    def save_data(self):
        self.root['trackers'] = self.trackers
        transaction.commit()

    def load_data(self):
        try:
            if 'trackers' not in self.root:
                self.root['trackers'] = {}
                self.root['next_id'] = 1  # Initialize the ID counter
                transaction.commit()
            self.trackers = self.root['trackers']
        except Exception as e:
            print(f"Warning: could not load data from '{self.db_path}': {str(e)}")
            self.trackers = {}

    def update_tracker(self, doc_id, tracker):
        self.trackers[doc_id] = tracker
        self.save_data()

    def delete_tracker(self, doc_id):
        if doc_id in self.trackers:
            del self.trackers[doc_id]
            self.save_data()

    def edit_tracker_history(self, label: str):
        tracker = self.get_tracker_from_label(label)
        if tracker:
            tracker.edit_history()
            self.save_data()
        else:
            print(f"No tracker found with ID {doc_id}.")

    def get_tracker_from_id(self, doc_id):
        return self.trackers.get(doc_id, None)

    def close(self):
        # Make sure to commit or abort any ongoing transaction
        print()
        try:
            if self.connection.transaction_manager.isDoomed():
                print("Transaction aborted.")
                transaction.abort()
            else:
                print("Transaction committed.")
                transaction.commit()
        except Exception as e:
            print(f"Error during transaction handling: {e}")
            transaction.abort()
        else:
            print("Transaction handled successfully.")
        finally:
            self.connection.close()

freq = 12

def format_statustime(obj, freq: int = 0):
    width = shutil.get_terminal_size()[0]
    ampm = True
    dayfirst = False
    yearfirst = True
    seconds = int(obj.strftime('%S'))
    dots = ' ' + (seconds // freq) * '.' if freq > 0 else ''
    month = obj.strftime('%b')
    day = obj.strftime('%-d')
    hourminutes = (
        obj.strftime(' %-I:%M%p').rstrip('M').lower()
        if ampm
        else obj.strftime(' %H:%M')
    ) + dots
    if width < 25:
        weekday = ''
        monthday = ''
    elif width < 30:
        weekday = f' {obj.strftime("%a")}'
        monthday = ''
    else:
        weekday = f'{obj.strftime("%a")}'
        monthday = f' {day} {month}' if dayfirst else f' {month} {day}'
    return f' {weekday}{monthday}{hourminutes}'

# Define the style
style = Style.from_dict({
    'menu-bar': f'bg:#396060 {NAMED_COLORS["White"]}',
    'display-area': f'bg:#1d3030 {NAMED_COLORS["White"]}',
    'input-area': f'bg:#1d3030 {NAMED_COLORS["Gold"]}',
    'message-window': f'bg:#396060 {NAMED_COLORS["White"]}',
    'status-window': f'bg:#396060 {NAMED_COLORS["White"]}',
})

def check_alarms():
    """Periodic task to check alarms."""
    while True:
        f = freq  # Interval (e.g., 6, 12, 30, 60 seconds)
        s = int(datetime.now().second)
        n = s % f
        w = f if n == 0 else f - n
        time.sleep(w)  # Wait for the next interval
        ct = datetime.now()
        current_time = format_statustime(ct, freq)
        message = f"{current_time}"
        update_status(message)

def update_status(new_message):
    status_control.text = new_message
    app.invalidate()  # Request a UI refresh

# UI Setup

def start_periodic_checks():
    """Start the periodic check for alarms in a separate thread."""
    threading.Thread(target=check_alarms, daemon=True).start()

def center_text(text, width: int = shutil.get_terminal_size()[0] - 2):
    if len(text) >= width:
        return text
    total_padding = width - len(text)
    left_padding = total_padding // 2
    right_padding = total_padding - left_padding
    return ' ' * left_padding + text + ' ' * right_padding

# all_trackers = center_text('All Trackers')

# Menu and Mode Control
menu_mode = [True]
select_mode = [False]
dialog_visible = [False]
input_visible = [False]
action = [None]

# Tracker mapping example
# UI Components
menu_text = "menu  a)dd d)elete e)dit i)nfo l)ist r)ecord s)how ^q)uit"
menu_container = Window(content=FormattedTextControl(text=menu_text), height=1, style="class:menu-bar")

search_field = SearchToolbar(
    text_if_not_searching=[
    ('class:not-searching', "Press '/' to start searching.")
    ],
    ignore_case=True,
    )
button = "  ⏺️"
label = " ▶️"
tag = "  🏷"
box = "■" # 0x2588
line_char = "━"
indent = "   "

# NOTE: zero-width space - to mark trackers with next <= today+oneday
BEF = '\u200B'

# display_text = f"""\
# Trackers
# {indent}{box}  name
# {indent}{line_char}  {line_char*30}
# """
display_text = f"""\
Trackers{BEF}
"""

# display_text = "Trackers\n"

trackers = {
    1: "fill birdfeeders",
    3: "fill water dispenser",
    5: "fill cat food dispenser",
    7: "fill dog food dispenser",
    9: "get haircut"
}

list_labels = [char for i, char in enumerate(string.ascii_lowercase)]
tracker_list = []
label_to_id = {}
index = 0
for k, v in trackers.items():
    label = list_labels[index]
    label_to_id[label] = k
    index += 1
    # NOTE: use BEF for trackers with next <= today + oneday
    if index <= 3:
        pre = BEF
    else:
        pre = ""
    tracker_list.append(f"{pre}{indent}{label}  {v} [{k}]")

display_text += "\n".join(tracker_list)

# display_text +=  "\n".join([f"{indent}{list_labels[k]}  Tracker {v}" for k, v in trackers.items()])

display_area = TextArea(text="initializing ...", read_only=True, search_field=search_field, style="class:display-area")

input_area = TextArea(focusable=True, multiline=True, height=3, prompt='> ', style="class:input-area")

dialog_visible = [False]
input_visible = [False]

input_container = ConditionalContainer(
    content=input_area,
    filter=Condition(lambda: input_visible[0])
)

message_control = FormattedTextControl(text="")
message_window = Window(content=message_control, height=1, style="class:message-window")

dialog_area = HSplit(
        [
            message_window,
            input_container,
        ]
    )

dialog_container = ConditionalContainer(
    content=dialog_area,
    filter=Condition(lambda: dialog_visible[0])
)

status_control = FormattedTextControl(text=f"{format_statustime(datetime.now(), freq)}")
status_window = Window(content=status_control, height=1, style="class:status-window")

def read_readme():
    try:
        with open("README.md", "r") as file:
            return file.read()
    except FileNotFoundError:
        return "README.md file not found."

# Application Setup
kb = KeyBindings()

key_msg = "Enter the label for the row of the tracker."

@kb.add('f1')
def menu(event=None):
    """Focus menu."""
    if event:
        if app.layout.has_focus(root_container.window):
            focus_previous(event)
            # app.layout.focus(root_container.body)
        else:
            app.layout.focus(root_container.window)

@kb.add('f2')
def do_about(*event):
    display_message('about track ...')

@kb.add('f3')
def do_check_updates(*event):
    display_message('update info ...')

@kb.add('f4')
def do_help(*event):
    help_text = read_readme()
    display_message(wrap(help_text, 0))

@kb.add('c-q')
def exit_app(*event):
    """Exit the application."""
    app.exit()

def display_message(message):
    """Log messages to the text area."""
    display_area.text = message
    message_control.text = ""
    app.invalidate()  # Refresh the UI

@kb.add('l', filter=Condition(lambda: menu_mode[0]))
def list_trackers(*event):
    """Add a new tracker."""
    action[0] = "list"
    menu_mode[0] = True
    select_mode[0] = False
    dialog_visible[0] = False
    input_visible[0] = False
    display_message(tracker_manager.list_trackers())
    # message_control.text = "Adding a new tracker..."
    app.layout.focus(display_area)

@kb.add('i', filter=Condition(lambda: menu_mode[0]))
def tracker_info(*event):
    """Show tracker information"""
    action[0] = "info"
    menu_mode[0] = True
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = f"For information, {key_msg}"
    # display_message(tracker_manager.list_trackers())
    # message_control.text = "Adding a new tracker..."
    # app.layout.focus(input_area)

@kb.add('a', filter=Condition(lambda: menu_mode[0]))
def add_tracker(*event):
    """Add a new tracker."""
    action[0] = "add"
    menu_mode[0] = False
    select_mode[0] = False
    input_visible[0] = True
    message_control.text = "Adding a new tracker..."
    app.layout.focus(input_area)

@kb.add('d', filter=Condition(lambda: menu_mode[0]))
def delete_tracker(*event):
    """Delete a tracker."""
    action[0] = "delete"
    menu_mode[0] = False
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = f"{key_msg} delete."

@kb.add('e', filter=Condition(lambda: menu_mode[0]))
def edit_history(*event):
    """Edit a tracker history."""
    action[0] = "edit"
    menu_mode[0] = False
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = f"{key_msg} edit."

def rename_tracker(*event):
    action[0] = "rename"
    menu_mode[0] = False
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = f"{key_msg} rename tracker."

# @kb.add('f4')
# def do_check_updates(*event):
#     display_message('Checking for updates...')
#     # status, res = check_update()
#     # '?', None (info unavalable)
#     # EtmChar.UPDATE_CHAR, available_version (update to available_version is possible)
#     # '', current_version (current_version is the latest available)
#     # if status in ['?', '']:   # message only
#     #     show_message('Update Information', res, 2)

def add_completion(self, completion_dt: datetime):
    action[0] = "add"
    menu_mode[0] = False
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = f"{key_msg} add completion."

    # ok, msg = True, ""
    # needs_sorting = False
    # if self.history and self.history[-1] >= completion_dt:
    #     print(f"""\
    # The new completion datetime
    #     {completion_dt}
    # is earlier than the previous completion datetime
    #     {self.history[-1]}.""")
    #     res = input("Is this what you wanted? (y/N): ").strip()
    #     if res.lower() not in ['y', 'yes']:
    #         return False, "aborted"
    #     needs_sorting = True

    # self.history.append(completion_dt)
    # if needs_sorting:
    #     self.history.sort()
    # if len(self.history) > Tracker.max_history:
    #     self.history = self.history[-Tracker.max_history:]

    # # Notify ZODB that this object has changed
    # self._p_changed = True

    return True, f"recorded completion for {completion_dt}"

def select_tracker(event, key: str):
    """Generic tracker selection."""
    tracker = tracker_manager.get_tracker_from_label(key)
    if tracker:
        selected_id = tracker.doc_id
        if action[0] == "edit":
            message_control.text = f"Editing tracker ID {selected_id}"
            dialog_visible[0] = True
            select_mode[0] = False
            input_visible[0] = True
            app.layout.focus(input_area)
        elif action[0] == "delete":
            message_control.text = f"Deleting tracker ID {selected_id}"
            select_mode[0] = False
            # Execute delete logic here
            app.layout.focus(display_area)
        elif action[0] == "add":
            message_control.text = f"Adding completion for tracker ID {selected_id}"
            select_mode[0] = False
            # Execute show logic here
        elif action[0] == "info":
            message_control.text = f"Showing tracker ID {selected_id}"
            select_mode[0] = False
            dialog_visible[0] = False
            input_visible[0] = False
            display_message(tracker.get_tracker_info())
            # Execute show logic here
            app.layout.focus(display_area)
        app.invalidate()

# Bind all lowercase letters to select_tracker
for key in string.ascii_lowercase:
    kb.add(key, filter=Condition(lambda: select_mode[0]))(lambda event, key=key: select_tracker(event, key))

# Layout


body = HSplit([
    # menu_container,
    display_area,
    search_field,
    status_window,
    dialog_container,  # Conditional Input Area
])

root_container = MenuContainer(
    body=body,
    menu_items=[
        MenuItem(
            'track',
            children=[
                MenuItem('F1) toggle menu', handler=menu),
                MenuItem('F2) about track', handler=do_about),
                MenuItem('F3) check for updates', handler=do_check_updates),
                MenuItem('F4) help', handler=do_help),
                MenuItem('^q) quit', handler=exit_app),
            ]
        ),
        MenuItem(
            'edit',
            children=[
                MenuItem('n) add new tracker', handler=add_tracker),
                MenuItem('c) add completion', handler=add_completion),
                MenuItem('d) delete tracker', handler=delete_tracker),
                MenuItem('e) edit completions', handler=edit_history),
                MenuItem('r) rename tracker', handler=rename_tracker),
            ]
        ),
        MenuItem(
            'view',
            children=[
                MenuItem('l) list trackers', handler=list_trackers),
                MenuItem('i) tracker info', handler=tracker_info),
            ]
        ),
    ]
)

layout = Layout(root_container)
# app = Application(layout=layout, key_bindings=kb, full_screen=True, style=style)

app = Application(layout=layout, key_bindings=kb, full_screen=True, mouse_support=True, style=style)

app.layout.focus(root_container.body)

tracker_manager = None
def main():
    global tracker_manager
    try:
        # TODO: use an environment variable or ~/.tracker/tracker.fs?
        db_file = "/Users/dag/track/tracker.fs"
        tracker_manager = TrackerManager(db_file)

        display_text = tracker_manager.list_trackers()
        print(display_text)
        display_message(display_text)


        start_periodic_checks()  # Start the periodic checks
        app.run()
    except Exception as e:
        print(f"exception raised:\n{e}")
    else:
        print("exited tracker", end="")
    finally:
        if tracker_manager:
            tracker_manager.close()
            print(f" and closed\n  {db_file}")
        else:
            print("")

if __name__ == "__main__":
    main()
