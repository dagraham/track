from typing import List, Dict, Any, Callable, Mapping
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.layout.containers import Window, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.widgets import TextArea, HorizontalLine, SearchToolbar
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style
from prompt_toolkit.styles.named_colors import NAMED_COLORS
from datetime import datetime, timedelta, date
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

# Tracker and TrackerManager classes here?
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

    def record_completion(self, completion_dt: datetime):
        ok, msg = True, ""
        needs_sorting = False
        if self.history and self.history[-1] >= completion_dt:
            print(f"""\
        The new completion datetime
            {completion_dt}
        is earlier than the previous completion datetime
            {self.history[-1]}.""")
            res = input("Is this what you wanted? (y/N): ").strip()
            if res.lower() not in ['y', 'yes']:
                return False, "aborted"
            needs_sorting = True

        self.history.append(completion_dt)
        if needs_sorting:
            self.history.sort()
        if len(self.history) > Tracker.max_history:
            self.history = self.history[-Tracker.max_history:]

        # Notify ZODB that this object has changed
        self._p_changed = True

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
            self._p_changed = True

        except ValueError:
            print("Invalid input. Please enter a number.")

    def get_tracker_data(self):
        last_completion = self.history[-1] if len(self.history) > 0 else None
        if len(self.history) > 1:
            intervals = [self.history[i+1] - self.history[i] for i in range(len(self.history) - 1)]
            num_intervals = len(intervals)
            average_interval = sum(intervals, timedelta()) / num_intervals
            last_interval = intervals[-1]
            change = last_interval - average_interval if last_interval >= average_interval else - (average_interval - last_interval)
            next_expected_completion = last_completion + average_interval
        else:
            intervals = []
            num_intervals = 0
            change = average_interval = last_interval = timedelta(minutes=0)
            next_expected_completion = None

        return f"""{self.name}
        completions ({len(self.history)}):
            last: {Tracker.format_dt(last_completion)}
            next: {Tracker.format_dt(next_expected_completion)}
        intervals ({len(intervals)}):
            average: {Tracker.format_td(average_interval)}
            last: {Tracker.format_td(last_interval)}
            change: {Tracker.format_td(change)}
        """

class TrackerManager:
    def __init__(self, db_path=None) -> None:
        if db_path is None:
            db_path = os.path.join(os.getcwd(), "tracker.fs")
        self.db_path = db_path
        self.trackers = {}
        self.storage = FileStorage.FileStorage(self.db_path)
        self.db = DB(self.storage)
        self.connection = self.db.open()
        self.root = self.connection.root()
        print(f"Opened tracker manager using data from\n  {self.db_path}")
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

    def list_trackers(self):
        print(f"all trackers:")
        for k, v in self.trackers.items():
            print(f"   {int(k):2> }. {v.name}")

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

    def edit_tracker_history(self, doc_id):
        tracker = self.get_tracker(doc_id)
        if tracker:
            tracker.edit_history()
            self.save_data()
        else:
            print(f"No tracker found with ID {doc_id}.")

    def get_tracker(self, doc_id):
        return self.trackers.get(doc_id, None)

    def close(self):
        self.connection.close()
        self.db.close()
        self.storage.close()


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
    if width < 50:
        weekday = ''
        monthday = ''
    elif width < 60:
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

# Application Setup

def start_periodic_checks():
    """Start the periodic check for alarms in a separate thread."""
    threading.Thread(target=check_alarms, daemon=True).start()

def center_text(text):
    line_length = shutil.get_terminal_size()[0] - 2
    if len(text) >= line_length:
        return text
    total_padding = line_length - len(text)
    left_padding = total_padding // 2
    right_padding = total_padding - left_padding
    return ' ' * left_padding + text + ' ' * right_padding

all_trackers = center_text('All Trackers')

# Menu and Mode Control
menu_mode = [True]
select_mode = [False]
dialog_visible = [False]
input_visible = [False]
action = [None]

# Tracker mapping example
trackers = {char: i+1 for i, char in enumerate(string.ascii_lowercase[:10])}

# UI Components
menu_text = "track  a)dd  d)elete  e)dit  i)nfo  r)ecord  ^q)uit "
menu_container = Window(content=FormattedTextControl(text=menu_text), height=1, style="class:menu-bar")

search_field = SearchToolbar(
    text_if_not_searching=[
    ('class:not-searching', "Press '/' to start searching.")
    ],
    ignore_case=True,
    )

display_text = "all trackers:\n" + "\n".join([f"  {k}. Tracker {v}" for k, v in trackers.items()])

display_area = TextArea(text=display_text, read_only=True, search_field=search_field, style="class:display-area")

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

# Layout
root_container = HSplit([
    menu_container,
    display_area,
    search_field,
    status_window,
    dialog_container,  # Conditional Input Area
])

layout = Layout(root_container)

# Application Setup
kb = KeyBindings()

@kb.add('c-q')
def exit_app(event):
    """Exit the application."""
    event.app.exit()

app = Application(layout=layout, key_bindings=kb, full_screen=True, style=style)

def log_to_text_area(message):
    """Log messages to the text area."""
    log_area.text += message + '\n'
    app.invalidate()  # Refresh the UI

@kb.add('a', filter=Condition(lambda: menu_mode[0]))
def add_tracker(event):
    """Add a new tracker."""
    action[0] = "add"
    menu_mode[0] = False
    select_mode[0] = False
    input_visible[0] = True
    message_control.text = "Adding a new tracker..."
    app.layout.focus(input_area)

@kb.add('d', filter=Condition(lambda: menu_mode[0]))
def delete_tracker(event):
    """Delete a tracker."""
    action[0] = "delete"
    menu_mode[0] = False
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = "Press the key corresponding to the tracker to delete."

@kb.add('e', filter=Condition(lambda: menu_mode[0]))
def edit_tracker(event):
    """Edit a tracker."""
    action[0] = "edit"
    menu_mode[0] = False
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = "Press the key corresponding to the tracker to edit."

def select_tracker(event, key):
    """Generic tracker selection."""
    if key in trackers:
        selected_id = trackers[key]
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
        app.invalidate()

# Bind all lowercase letters to select_tracker
for key in string.ascii_lowercase:
    kb.add(key, filter=Condition(lambda: select_mode[0]))(lambda event, key=key: select_tracker(event, key))

app = Application(layout=layout, key_bindings=kb, full_screen=True, style=style)

def main():
    try:
        tracker_manager = TrackerManager("/Users/dag/tracker-dgraham/tracker.fs")

        start_periodic_checks()  # Start the periodic checks
        app.run()
    finally:
        if tracker_manager:
            tracker_manager.close()
            print("Closed tracker manager")

if __name__ == "__main__":
    main()
