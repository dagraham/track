#!/usr/bin/env python3
from typing import List, Dict, Any, Callable, Mapping
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    HSplit,
    VSplit,
    Window,
    WindowAlign,
    ConditionalContainer,
)
# from prompt_toolkit.layout.containers import Window, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.keys import Keys
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
from dateutil.parser import parse, parserinfo
import string
import shutil
import threading
import traceback
import sys
import logging
from ZODB import DB, FileStorage
from persistent import Persistent
import transaction
import os
import time

import textwrap
import re
import __version__ as version

tracker_manager = None

# Non-printing character
NON_PRINTING_CHAR = '\u200B'
# Placeholder for spaces within special tokens
PLACEHOLDER = '\u00A0'
# Placeholder for hyphens to prevent word breaks
NON_BREAKING_HYPHEN = '\u2011'

# For showing active page in pages, e.g.,  ○ ○ ⏺ ○ = page 3 of 4 pages
OPEN_CIRCLE = '○'
CLOSED_CIRCLE = '⏺'

def page_banner(active_page_num: int, number_of_pages: int):
    markers = []
    for i in range(1, number_of_pages + 1):
        marker = CLOSED_CIRCLE if i == active_page_num else OPEN_CIRCLE
        markers.append(marker)
    return ' '.join(markers)

# Console logging
def setup_console_logging():
    # Default logging level
    log_level = logging.INFO

    # Check if a logging level argument was provided
    if len(sys.argv) > 1:
        try:
            # Convert the argument to an integer and set it as the logging level
            log_level = int(sys.argv[1])
        except ValueError:
            print(f"Invalid log level: {sys.argv[1]}. Using default INFO level.")

    # Configure logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logging.info(f"Logging initialized at level {log_level}")

# File logging
def setup_file_logging():
    log_level = logging.INFO

    if len(sys.argv) > 1:
        try:
            log_level = int(sys.argv[1])
        except ValueError:
            print(f"Invalid log level: {sys.argv[1]}. Using default INFO level.")

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        filename="/Users/dag/track-test/logs/tracker.log",  # Output to a file only
        filemode="a"  # Append to the file
    )
    logging.info(f"Logging initialized at level {log_level}")

# make logging available globally
setup_file_logging()
logger = logging.getLogger()

logger.debug(f"version: {version.version}")

def wrap(text: str, indent: int = 3, width: int = shutil.get_terminal_size()[0] - 2):
    # Preprocess to replace spaces within specific "@\S" patterns with PLACEHOLDER
    text = preprocess_text(text)
    numbered_list = re.compile(r'^\d+\.\s.*')

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
        # elif stripped_para and stripped_para[0].isdigit():
        elif stripped_para and numbered_list.match(stripped_para):
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
    max_history = 12 # depending on width, 6 rows of 2, 4 rows of 3, 3 rows of 4, 2 rows of 6

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
                days_str = 'days' if days > 1 else 'day'
                until.append(f'{days} {days_str}')
            if hours:
                hours_str = 'hours' if hours > 1 else 'hour'
                until.append(f'{hours} {hours_str}')
            if minutes:
                minutes_str = 'minutes' if minutes > 1 else 'minute'
                until.append(f'{minutes} {minutes_str}')
            if not until:
                until.append('0 minutes')
            ret = sign + ' '.join(until)
            return ret
        except Exception as e:
            logger.debug(f'{td}: {e}')
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
                logger.debug(f"Error parsing datetime: {dt}\ne {repr(e)}\n{traceback.format_exc()}", file=sys.stderr, flush=True)
                return None
        else:
            return None

    def __init__(self, name: str, doc_id: int) -> None:
        self.doc_id = int(doc_id)
        self.name = name
        self.history = []
        logger.debug(f"Created tracker {self.name} ({self.doc_id})")


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
            intervals = []
            result['num_intervals'] = 0
            result['change'] = result['average_interval'] = result['last_interval'] = None
            result['next_expected_completion'] = None
            if result['num_completions'] > 0:
                intervals = [self.history[i+1] - self.history[i] for i in range(len(self.history) - 1)]
                result['num_intervals'] = len(intervals)
            if result['num_intervals'] > 0:
                result['last_interval'] = intervals[-1]
            if result['num_intervals'] > 1:
                result['average_interval'] = sum(intervals, timedelta()) / result['num_intervals']
                result['next_expected_completion'] = result['last_completion'] + result['average_interval']
            if result['num_intervals'] > 2:
                if result['last_interval'] >= result['average_interval']:
                    result['change'] = result['last_interval'] - result['average_interval']
                else:
                    result['change'] = - (result['average_interval'] - result['last_interval'])
        self._p_changed = True
        # logger.debug(f"returning {result = }")
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
        self.history.append(completion_dt)
        self.history.sort()
        if len(self.history) > Tracker.max_history:
            self.history = self.history[-Tracker.max_history:]

        # Notify ZODB that this object has changed
        self.invalidate_info()
        self._p_changed = True
        return True, f"recorded completion for {completion_dt}"

    def edit_history(self):
        if not self.history:
            logger.debug("No history to edit.")
            return

        # Display current history
        for i, dt in enumerate(self.history):
            logger.debug(f"{i + 1}. {self.format_dt(dt)}")

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
        format_str = f"%y-%m-%d{PLACEHOLDER}%H:%M"
        history = ', '.join(x.strftime(format_str) for x in self.history)
        return wrap(f"""\
 {self.name}
   doc_id: {self.doc_id}
   completions ({self._info['num_completions']}):
       last: {Tracker.format_dt(self._info['last_completion'])}
       next: {Tracker.format_dt(self._info['next_expected_completion'])}
   intervals ({self._info['num_intervals']}):
       average: {Tracker.format_td(self._info['average_interval'])}
       last: {Tracker.format_td(self._info['last_interval'])}
       change: {Tracker.format_td(self._info['change'])}
   history:
       {history}""", 0)

class TrackerManager:
    labels = "abcdefghijklmnopqrstuvwxyz"

    def __init__(self, db_path=None) -> None:
        if db_path is None:
            db_path = os.path.join(os.getcwd(), "tracker.fs")
        self.db_path = db_path
        self.trackers = {}
        self.label_to_id = {}
        self.row_to_id = {}
        self.active_page = 0
        self.storage = FileStorage.FileStorage(self.db_path)
        self.db = DB(self.storage)
        self.connection = self.db.open()
        self.root = self.connection.root()
        logger.debug(f"opened tracker manager using data from\n  {self.db_path}")
        self.load_data()

    def load_data(self):
        try:
            if 'trackers' not in self.root:
                self.root['trackers'] = {}
                self.root['next_id'] = 1  # Initialize the ID counter
                transaction.commit()
            self.trackers = self.root['trackers']
        except Exception as e:
            logger.debug(f"Warning: could not load data from '{self.db_path}': {str(e)}")
            self.trackers = {}

    def add_tracker(self, name: str) -> None:
        doc_id = self.root['next_id']
        # Create a new tracker with the current doc_id
        tracker = Tracker(name, doc_id)
        # Add the tracker to the trackers dictionary
        self.trackers[doc_id] = tracker
        # Increment the next_id for the next tracker
        self.root['next_id'] += 1
        # Save the updated data
        self.save_data()

        logger.debug(f"Tracker '{name}' added with ID {doc_id}")


    def record_completion(self, doc_id: int, dt: datetime):
        # dt will be a datetime
        ok, msg = self.trackers[doc_id].record_completion(dt)
        if not ok:
            display_message(msg)
            return
        display_message(f"""\
Recorded completion {dt.strftime('%Y-%m-%d %H:%M')}\n {self.trackers[doc_id].get_tracker_info()}""")

    # def get_tracker_data(self, doc_id: int = None):
    #     if doc_id is None:
    #         logger.debug("data for all trackers:")
    #         for k, v in self.trackers.items():
    #             logger.debug(f"   {k:2> }. {v.get_tracker_data()}")
    #     elif doc_id in self.trackers:
    #         logger.debug(f"data for tracker {doc_id}:")
    #         logger.debug(f"   {doc_id:2> }. {self.trackers[doc_id].get_tracker_data()}")

    def sort_key(self, tracker):
        next_dt = tracker._info.get('next_expected_completion', None) if hasattr(tracker, '_info') else None
        last_dt = tracker._info.get('last_completion', None) if hasattr(tracker, '_info') else None
        if next_dt:
            return (2, next_dt)
        if last_dt:
            return (1, last_dt)
        return (0, tracker.doc_id)


    def get_sorted_trackers(self):
        # Extract the list of trackers
        trackers = [v for k, v in self.trackers.items()]
        # Sort the trackers
        return sorted(trackers, key=self.sort_key)

    def list_trackers(self):
        num_pages = (len(self.trackers) + 25) // 26
        # page_banner = f" (page {self.active_page + 1}/{num_pages})"
        set_pages(page_banner(self.active_page + 1, num_pages))
        banner = f" tag     next      last      tracker name\n"
        rows = []
        count = 0
        start_index = self.active_page * 26
        end_index = start_index + 26
        sorted_trackers = self.get_sorted_trackers()
        for tracker in sorted_trackers[start_index:end_index]:
            next_dt = tracker._info.get('next_expected_completion', None) if hasattr(tracker, '_info') else None
            last_dt = tracker._info.get('last_completion', None) if hasattr(tracker, '_info') else None
            # next = next_dt.strftime("%a %b %-d") if next_dt else center_text("~", 10)
            next = next_dt.strftime("%y-%m-%d") if next_dt else center_text("~", 8)
            last = last_dt.strftime("%y-%m-%d") if last_dt else center_text("~", 8)
            label = TrackerManager.labels[count]
            self.label_to_id[(self.active_page, label)] = tracker.doc_id
            self.row_to_id[(self.active_page, count+1)] = tracker.doc_id
            count += 1
            rows.append(f" {label}     {next:<8}  {last:<8}  {tracker.name}")
        return banner +"\n".join(rows)

    def set_active_page(self, page_num):
        if 0 <= page_num < (len(self.trackers) + 25) // 26:
            self.active_page = page_num
        else:
            logger.debug("Invalid page number.")

    def next_page(self):
        self.set_active_page(self.active_page + 1)

    def previous_page(self):
        self.set_active_page(self.active_page - 1)

    def get_tracker_from_label(self, label: str):
        pagelabel = (self.active_page, label)
        if pagelabel not in self.label_to_id:
            return None
        return self.trackers[self.label_to_id[pagelabel]]

    def get_tracker_from_row(self, row: int):
        pagerow = (self.active_page, row)
        if pagerow not in self.row_to_id:
            return None
        return self.trackers[self.row_to_id[pagerow]]

    def save_data(self):
        self.root['trackers'] = self.trackers
        transaction.commit()

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
            logger.debug(f"No tracker found with ID {doc_id}.")

    def get_tracker_from_id(self, doc_id):
        return self.trackers.get(doc_id, None)

    def close(self):
        # Make sure to commit or abort any ongoing transaction
        print()
        try:
            if self.connection.transaction_manager.isDoomed():
                logger.error("Transaction aborted.")
                transaction.abort()
            else:
                logger.info("Transaction committed.")
                transaction.commit()
        except Exception as e:
            logger.error(f"Error during transaction handling: {e}")
            transaction.abort()
        else:
            logger.info("Transaction handled successfully.")
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

display_area = TextArea(text="initializing ...", read_only=True, search_field=search_field, style="class:display-area")

input_area = TextArea(focusable=True, multiline=True, height=3, prompt='> ', style="class:input-area")

dialog_visible = [False]
input_visible = [False]
action = [None]

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

page_control = FormattedTextControl(text="")
page_window = Window(content=page_control, height=1, style="class:status-window", width=shutil.get_terminal_size()[0]//2, align=WindowAlign.LEFT)


def set_pages(txt: str):
    page_control.text = f"{txt} "


status_area = VSplit(
    [
        status_window,
        page_window,
    ],
    height=1,
)


def get_row_col():
    row_number = display_area.document.cursor_position_row
    col_number = display_area.document.cursor_position_col
    return row_number, col_number

def get_tracker_from_row()->int:
    row = display_area.document.cursor_position_row
    page = tracker_manager.active_page
    id = tracker_manager.row_to_id.get((page, row), None)
    logger.debug(f"{page = }, {row = } => {id = }")
    if id is not None:
        tracker = tracker_manager.get_tracker_from_id(id)
    else:
        tracker = None
    return tracker

def read_readme():
    try:
        with open("README.md", "r") as file:
            return file.read()
    except FileNotFoundError:
        return "README.md file not found."

# Application Setup
kb = KeyBindings()

key_msg = "enter the letter for the tracker row."

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
    """List trackers."""
    action[0] = "list"
    menu_mode[0] = True
    select_mode[0] = False
    dialog_visible[0] = False
    input_visible[0] = False
    display_message(tracker_manager.list_trackers())
    # message_control.text = "Adding a new tracker..."
    app.layout.focus(display_area)
    app.invalidate()

@kb.add('right', filter=Condition(lambda: menu_mode[0]))
def next_page(*event):
    logger.debug("next page")
    tracker_manager.next_page()
    list_trackers()

@kb.add('left', filter=Condition(lambda: menu_mode[0]))
def previous_page(*event):
    logger.debug("previous page")
    tracker_manager.previous_page()
    list_trackers()



def close_dialog(*event):
    action[0] = ""
    message_control.text = ""
    input_area.text = ""
    menu_mode[0] = True
    dialog_visible[0] = False
    input_visible[0] = False
    app.layout.focus(display_area)

@kb.add('i', filter=Condition(lambda: menu_mode[0]))
def tracker_info(*event):
    """Show tracker information"""
    tracker = get_tracker_from_row()
    logger.debug(f"in tracker_info: {tracker = }")
    action[0] = "info"
    if tracker:
        logger.debug("got tracker from row, calling process_tracker")
        menu_mode[0] = True
        select_mode[0] = False
        dialog_visible[0] = True
        input_visible[0] = True
        process_tracker(event, tracker)
    else:
        logger.debug("using label selection")
        menu_mode[0] = True
        select_mode[0] = True
        dialog_visible[0] = True
        input_visible[0] = False
        message_control.text = f"For information, {key_msg}"
    # display_message(tracker_manager.list_trackers())
    # message_control.text = "Adding a new tracker..."
    # app.layout.focus(input_area)

@kb.add('n', filter=Condition(lambda: menu_mode[0]))
def new_tracker(*event):
    """Add a new tracker."""
    action[0] = "new"
    menu_mode[0] = False
    select_mode[0] = False
    dialog_visible[0] = True
    input_visible[0] = True
    message_control.text = " Enter the name for the new tracker"
    logger.debug(f"action: {action[0]} getting tracker name ...")
    app.layout.focus(input_area)

    input_area.accept_handler = lambda buffer: handle_input()

    @kb.add('c-s', filter=Condition(lambda: action[0]=="new"))
    def handle_input(event):
        """Handle input when Enter is pressed."""
        tracker_name = input_area.text.strip()
        if tracker_name:
            logger.debug(f"got tracker name: {tracker_name}")
            tracker_manager.add_tracker(tracker_name)
            input_area.text = ""
            list_trackers()
        else:
            message_control.text = "No tracker name provided."
            list_trackers()

@kb.add('c-e')
def add_example_trackers(*event):
    for i in range(100):
        tracker_manager.add_tracker(f"example {i+1}")
    list_trackers()

@kb.add('c-r')
def del_example_trackers(*event):
    remove = []
    for id, tracker in tracker_manager.trackers.items():
        if tracker.name.startswith('example'):
            remove.append(id)
    for id in remove:
        tracker_manager.delete_tracker(id)
    list_trackers()

@kb.add('c', filter=Condition(lambda: menu_mode[0]))
def add_completion(*event):
    action[0] = "complete"
    logger.debug(f"action: '{action[0]}'")
    menu_mode[0] = False
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = f"{key_msg} add completion."

@kb.add('c-s', filter=Condition(lambda: action[0]=="complete"))
def handle_completion(event):
    """Handle input when Enter is pressed."""
    completion_str = input_area.text.strip()
    logger.debug(f"got completion_str: '{completion_str}' for {selected_id}")
    if completion_str:
        completion_dt = Tracker.parse_dt(completion_str)
        logger.debug(f"recording completion_dt: '{completion_dt}' for {selected_id}")
        tracker_manager.record_completion(selected_id, completion_dt)
        # input_area.text = ""
        # dialog_visible[0] = False
        # input_visible[0] = False
        close_dialog()
    else:
        display_area.text = "No completion datetime provided."
    # app.layout.focus(display_area)

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

selected_id = None
def select_tracker_from_label(event, key: str):
    """Generic tracker selection."""
    global selected_id
    tracker = tracker_manager.get_tracker_from_label(key)
    selected_id = tracker.doc_id
    if tracker:
        logger.debug("got tracker from label, calling process_tracker")
        selected_id = tracker.doc_id
        select_mode[0] = False
        process_tracker(event, tracker)
    else:
        list_trackers()

def process_tracker(event, tracker: Tracker = None):
    global selected_id
    logger.debug("in process_tracker")
    if tracker:
        logger.debug("   with tracker")
        selected_id = tracker.doc_id
        logger.debug(f"{action[0] = }; {selected_id = }")
        if action[0] == "edit":
            message_control.text = f"Editing tracker {tracker.name} ({selected_id})"
            dialog_visible[0] = True
            select_mode[0] = False
            input_visible[0] = True
            app.layout.focus(input_area)
        elif action[0] == "delete":
            message_control.text = f"Deleting tracker {tracker.name} ({selected_id})"
            select_mode[0] = False
            tracker_manager.delete_tracker(selected_id)
            list_trackers()
            app.layout.focus(display_area)
        elif action[0] == "complete":
            message_control.text = f"Enter the new completion datetime for {tracker.name} ({selected_id})"
            # logger.debug(f"Entering the new completion datetime for {tracker.name} ({selected_id})")
            select_mode[0] = False
            dialog_visible[0] = True
            input_visible[0] = True
            app.layout.focus(input_area)
            input_area.accept_handler = lambda buffer: handle_completion()
        elif action[0] == "info":
            logger.debug(f"in 'info' ")
            message_control.text = f"Showing tracker ID {selected_id}"
            select_mode[0] = False
            dialog_visible[0] = False
            input_visible[0] = False
            info = tracker.get_tracker_info()
            logger.debug(f"{info = }")
            display_message(tracker.get_tracker_info())
            app.layout.focus(display_area)
        app.invalidate()
    else:
        list_trackers()

# Bind all lowercase letters to select_tracker
keys = list(string.ascii_lowercase)
keys.append('escape')
for key in keys:
    kb.add(key, filter=Condition(lambda: select_mode[0]), eager=True)(lambda event, key=key: select_tracker_from_label(event, key))

# Layout


body = HSplit([
    # menu_container,
    display_area,
    search_field,
    status_area,
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
                MenuItem('n) add new tracker', handler=new_tracker),
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
        db_file = "/Users/dag/track-test/tracker.fs"
        logging.info(f"Starting TrackerManager with database file {db_file}")
        tracker_manager = TrackerManager(db_file)

        display_text = tracker_manager.list_trackers()
        logging.debug(f"Tracker list: {display_text}")
        display_message(display_text)


        start_periodic_checks()  # Start the periodic checks
        app.run()
    except Exception as e:
        logger.debug(f"exception raised:\n{e}")
    else:
        logger.debug("exited tracker")
    finally:
        if tracker_manager:
            tracker_manager.close()
            logging.info(f"Closed TrackerManager and database file {db_file}")
            # logger.debug(f" and closed\n  {db_file}")
        else:
            logging.info("TrackerManager was not initialized")
            print("")

if __name__ == "__main__":
    main()
