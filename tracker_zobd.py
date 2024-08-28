#!/usr/bin/env python3
from typing import List, Dict, Any, Callable, Mapping
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    HSplit,
    VSplit,
    Window,
    DynamicContainer,
    WindowAlign,
    ConditionalContainer,
)
from prompt_toolkit.layout.dimension import D
# from prompt_toolkit.layout.containers import Window, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style
from prompt_toolkit.styles.named_colors import NAMED_COLORS
from prompt_toolkit.lexers import Lexer

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
from prompt_toolkit.application.current import get_app

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
import json

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
# Placeholder for zero-width non-joiner
ZWNJ = '\u200C'

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
        logging.info(f"\n### Logging initialized at level {log_level} ###")

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
        # format="%(asctime)s [%(levelname)s] %(message)s",

        format='--- %(asctime)s - %(levelname)s - %(module)s.%(funcName)s\n    %(message)s',
        datefmt="%Y-%m-%d %H:%M:%S",
        filename="/Users/dag/track-test/logs/tracker.log",  # Output to a file only
        filemode="a"  # Append to the file
    )
    logging.info(f"\n### Logging initialized at level {log_level} ###")

# make logging available globally
setup_file_logging()
logger = logging.getLogger()

logger.debug(f"version: {version.version}")

### Begin Backup and Restore functions
def serialize_record(record):
    def convert_value(value):
        if isinstance(value, datetime):
            return value.strftime("%y%m%dT%H%M")  # Convert datetime to ISO format string
        elif isinstance(value, timedelta):
            return str(int(value.total_seconds()/60))  # Convert timedelta to minutes
        elif isinstance(value, tuple) and len(value) == 2:
            if isinstance(value[0], datetime) and isinstance(value[1], timedelta):
                return (value[0].strftime("%y%m%dT%H%M"), str(int(value[1].total_seconds()/60)))
            else:
                return tuple(convert_value(v) for v in value)
        elif isinstance(value, list):
            return [convert_value(v) for v in value]  # Process each element in the list
        elif isinstance(value, dict):
            return {k: convert_value(v) for k, v in value.items()}
        else:
            return value

    return convert_value(record)

def deserialize_record(record):
    def convert_value(value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
            try:
                return timedelta(seconds=float(value))
            except ValueError:
                pass
        if isinstance(value, tuple) and len(value) == 2:
            try:
                dt = datetime.fromisoformat(value[0])
                td = timedelta(seconds=float(value[1]))
                return (dt, td)
            except ValueError:
                return tuple(convert_value(v) for v in value)
        elif isinstance(value, list):
            return [convert_value(v) for v in value]  # Process each element in the list
        elif isinstance(value, dict):
            return {k: convert_value(v) for k, v in value.items()}
        else:
            return value

    return convert_value(record)

def backup_zodb_to_json(root, json_file):
    # Open ZODB
    # storage = FileStorage.FileStorage(db_file)
    # db = DB(storage)
    # connection = db.open()
    # root = connection.root()

    # Convert the ZODB data to a JSON serializable format
    json_data = {k: serialize_record(v) for k, v in root.items()}

    # Write the data to a JSON file
    with open(json_file, 'w') as json_file:
        json.dump(json_data, json_file, indent=2)

    # Close ZODB
    # connection.close()
    # db.close()
    # storage.close()
    # return True

# Example usage
# backup_zodb_to_json(db_file, json_file)

def restore_json_to_zodb(json_file_path, zodb_path):
    # Open ZODB
    storage = FileStorage.FileStorage(zodb_path)
    db = DB(storage)
    connection = db.open()
    root = connection.root()

    # Load the JSON data
    with open(json_file_path, 'r') as json_file:
        json_data = json.load(json_file)

    # Convert the JSON data back to the original format and restore to ZODB
    for k, v in json_data.items():
        root[k] = deserialize_record(v)

    # Commit the transaction to save changes
    transaction.commit()

    # Close ZODB
    connection.close()
    db.close()
    storage.close()

# Example usage
# restore_json_to_zodb('/path/to/backup.json', '/path/to/your/Data.fs')

### End Backup and Restore functions

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
        return dt.strftime("%y%m%dT%H%M")

    @classmethod
    def td2seconds(cls, td: timedelta) -> str:
        if not isinstance(td, timedelta):
            return ""
        return f"{round(td.total_seconds())}"

    @classmethod
    def format_td(cls, td: timedelta):
        if not isinstance(td, timedelta):
            return None
        sign = '+' if td.total_seconds() >= 0 else '-'
        total_seconds = abs(int(td.total_seconds()))
        if total_seconds == 0:
            # return '0 minutes '
            return '+0m'
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
                # days_str = 'days' if days > 1 else 'day'
                days_str = 'd'
                until.append(f'{days}{days_str}')
            if hours:
                # hours_str = 'hours' if hours > 1 else 'hour'
                hours_str = 'h'
                until.append(f'{hours}{hours_str}')
            if minutes:
                # minutes_str = 'minutes' if minutes > 1 else 'minute'
                minutes_str = 'm'
                until.append(f'{minutes}{minutes_str}')
            if not until:
                until.append('+0m')
            ret = sign + ''.join(until)
            return ret
        except Exception as e:
            logger.debug(f'{td}: {e}')
            return ''

    @classmethod
    def format_completion(cls, completion: tuple[datetime, timedelta])->str:
        dt, td = completion
        return f"{cls.format_dt(dt)}, {cls.format_td(td)}"

    @classmethod
    def parse_td(cls, td)->tuple[bool, timedelta]:
        """\
        Take a period string and return a corresponding timedelta.
        Examples:
            parse_duration('-2w3d4h5m')= Duration(weeks=-2,days=3,hours=4,minutes=5)
            parse_duration('1h30m') = Duration(hours=1, minutes=30)
            parse_duration('-10m') = Duration(minutes=10)
        where:
            d: days
            h: hours
            m: minutes
            s: seconds

        >>> 3*60*60+5*60
        11100
        >>> parse_duration("2d-3h5m")[1]
        Duration(days=1, hours=21, minutes=5)
        >>> datetime(2015, 10, 15, 9, 0, tz='local') + parse_duration("-25m")[1]
        DateTime(2015, 10, 15, 8, 35, 0, tzinfo=ZoneInfo('America/New_York'))
        >>> datetime(2015, 10, 15, 9, 0) + parse_duration("1d")[1]
        DateTime(2015, 10, 16, 9, 0, 0, tzinfo=ZoneInfo('UTC'))
        >>> datetime(2015, 10, 15, 9, 0) + parse_duration("1w-2d+3h")[1]
        DateTime(2015, 10, 20, 12, 0, 0, tzinfo=ZoneInfo('UTC'))
        """

        knms = {
            'd': 'days',
            'day': 'days',
            'days': 'days',
            'h': 'hours',
            'hour': 'hours',
            'hours': 'hours',
            'm': 'minutes',
            'minute': 'minutes',
            'minutes': 'minutes',
            's': 'seconds',
            'second': 'second',
            'seconds': 'seconds',
        }

        kwds = {
            'days': 0,
            'hours': 0,
            'minutes': 0,
            'seconds': 0,
        }

        period_regex = re.compile(r'(([+-]?)(\d+)([dhms]))+?')
        expanded_period_regex = re.compile(r'(([+-]?)(\d+)\s(day|hour|minute|second)s?)+?')
        logger.debug(f"parse_td: {td}")
        m = period_regex.findall(td)
        if not m:
            m = expanded_period_regex.findall(str(s))
            if not m:
                return False, f"Invalid period string '{s}'"
        for g in m:
            if g[3] not in knms:
                return False, f'Invalid period argument: {g[3]}'

            num = -int(g[2]) if g[1] == '-' else int(g[2])
            if num:
                kwds[knms[g[3]]] = num
        td = timedelta(**kwds)
        return True, td


    @classmethod
    def parse_dt(cls, dt: str = "") -> tuple[bool, datetime]:
        # if isinstance(dt, datetime):
        #     return True, dt
        if dt.strip() == "now":
            dt = datetime.now()
            return True, dt
        elif isinstance(dt, str) and dt:
            pi = parserinfo(
                dayfirst=False,
                yearfirst=True)
            try:
                dt = parse(dt, parserinfo=pi)
                return True, dt
            except Exception as e:
                msg = f"Error parsing datetime: {dt}\ne {repr(e)}"
                return False, msg
        else:
            return False, "Invalid datetime"

    @classmethod
    def parse_completion(cls, completion: str) -> tuple[datetime, timedelta]:
        parts = [x.strip() for x in re.split(r',\s+', completion)]
        dt = parts.pop(0)
        if parts:
            td = parts.pop(0)
        else:
            td = timedelta(0)

        logger.debug(f"parts: {dt}, {td}")
        msg = []
        if not dt:
            return False, ""
        dtok, dt = cls.parse_dt(dt)
        if not dtok:
            msg.append(dt)
        if td:
            logger.debug(f"{td = }")
            tdok, td = cls.parse_td(td)
            if not tdok:
                msg.append(td)
        else:
            # no td specified
            td = timedelta(0)
            tdok = True
        if dtok and tdok:
            return True, (dt, td)
        return False, "; ".join(msg)



    def __init__(self, name: str, doc_id: int) -> None:
        self.doc_id = int(doc_id)
        self.name = name
        self.history = []
        self.created = datetime.now()
        self.modifed = self.created
        logger.debug(f"Created tracker {self.name} ({self.doc_id})")


    @property
    def info(self):
        # Lazy initialization with re-computation logic
        if not hasattr(self, '_info') or self._info is None:
            logger.debug(f"Computing info for {self.name} ({self.doc_id})")
            self._info = self.compute_info()
        return self._info

    def compute_info(self):
        # Example computation based on history, returning a dict
        result = {}
        logger.debug(f"got here")
        if not self.history:
            result = dict(
                last_completion=None, num_completions=0, num_intervals=0, average_interval=timedelta(minutes=0), last_interval=timedelta(minutes=0), spread=timedelta(minutes=0), next_expected_completion=None,
                early=None, late=None
                )
        else:
            result['last_completion'] = self.history[-1] if len(self.history) > 0 else None
            result['num_completions'] = len(self.history)
            intervals = []
            result['num_intervals'] = 0
            result['spread'] = None
            result['last_interval'] = None
            result['average_interval'] = None
            result['next_expected_completion'] = None
            result['early'] = None
            result['late'] = None
            if result['num_completions'] > 0:
                for i in range(len(self.history)-1):
                    #                      x[i+1]                  y[i+1]               x[i]
                    logger.debug(f"{self.history[i+1]}")
                    intervals.append(self.history[i+1][0] + self.history[i+1][1] - self.history[i][0])
                result['num_intervals'] = len(intervals)
            if result['num_intervals'] > 0:
                result['last_interval'] = intervals[-1]
                if result['num_intervals'] == 1:
                    result['average_interval'] = intervals[-1]
                else:
                    result['average_interval'] = sum(intervals, timedelta()) / result['num_intervals']
                result['next_expected_completion'] = result['last_completion'][0] + result['average_interval']
            if result['num_intervals'] >= 2:
                total = timedelta(minutes=0)
                for interval in intervals:
                    if interval < result['average_interval']:
                        total += result['average_interval'] - interval
                    else:
                        total += interval - result['average_interval']
                result['spread'] = total / result['num_intervals']
                result['early'] = result['next_expected_completion'] - result['spread']
                result['late'] = result['next_expected_completion'] + result['spread']
        self._p_changed = True
        logger.debug(f"returning {result = }")
        return result

    # XXX: Just for reference
    def add_to_history(self, new_event):
        self.history.append(new_event)
        self.modifed = datetime.now()
        self.invalidate_info()
        self._p_changed = True  # Mark object as changed in ZODB

    def invalidate_info(self):
        # Invalidate the cached dict so it will be recomputed on next access
        if hasattr(self, '_info'):
            delattr(self, '_info')


    def record_completion(self, completion: tuple[datetime, timedelta]):
        ok, msg = True, ""
        self.history.append(completion)
        self.history.sort(key=lambda x: x[0])
        if len(self.history) > Tracker.max_history:
            self.history = self.history[-Tracker.max_history:]

        # Notify ZODB that this object has changed
        self.invalidate_info()
        self.modifed = datetime.now()
        self._p_changed = True
        return True, f"recorded completion for ..."

    def edit_history(self):
        if not self.history:
            logger.debug("No history to edit.")
            return

        # Display current history
        for i, completion in enumerate(self.history):
            logger.debug(f"{i + 1}. {self.format_completion(completion)}")

        # Choose an entry to edit
        try:
            choice = int(input("Enter the number of the history entry to edit (or 0 to cancel): ").strip())
            if choice == 0:
                return
            if choice < 1 or choice > len(self.history):
                print("Invalid choice.")
                return
            selected_comp = self.history[choice - 1]
            print(f"Selected completion: {self.format_completion(selected_comp)}")

            # Choose what to do with the selected entry
            action = input("Do you want to (d)elete or (r)eplace this entry? ").strip().lower()

            if action == 'd':
                self.history.pop(choice - 1)
                print("Entry deleted.")
            elif action == 'r':
                new_comp_str = input("Enter the replacement completion: ").strip()
                ok, new_comp = self.parse_completion(new_comp_str)
                if ok:
                    self.history[choice - 1] = new_comp
                    return True, f"Entry replaced with {self.format_completion(new_comp)}"
                else:
                    return False, f"{new_comp}"
            else:
                return False, "Invalid action."

            # Sort and truncate history if necessary
            self.history.sort()
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]

            # Notify ZODB that this object has changed
            self.modifed = datetime.now()
            self.update_tracker_info()
            self.invalidate_info()
            self._p_changed = True

        except ValueError:
            print("Invalid input. Please enter a number.")

    def get_tracker_info(self):
        if not hasattr(self, '_info') or self._info is None:
            self._info = self.compute_info()
        # insert a placeholder to prevent date and time from being split across multiple lines when wrapping
        # format_str = f"%y-%m-%d{PLACEHOLDER}%H:%M"
        logger.debug(f"{self.history = }")
        history = [f"{Tracker.format_dt(x[0])} {Tracker.format_td(x[1])}" for x in self.history]
        history = ', '.join(history)
        return wrap(f"""\
 name:        {self.name}
 doc_id:      {self.doc_id}
 created:     {Tracker.format_dt(self.created)}
 modified:    {Tracker.format_dt(self.modifed)}
 completions: ({self._info['num_completions']})
    {history}
 intervals:   ({self._info['num_intervals']})
    last:     {Tracker.format_td(self._info['last_interval'])}
    average:  {Tracker.format_td(self._info['average_interval'])}
    spread:   {Tracker.format_td(self._info['spread'])}
 next:        {Tracker.format_dt(self._info['next_expected_completion'])}
    early:    {Tracker.format_dt(self._info.get('early', '?'))}
    late:     {Tracker.format_dt(self._info.get('late', '?'))}
""", 0)

class TrackerManager:
    labels = "abcdefghijklmnopqrstuvwxyz"

    def __init__(self, db_path=None) -> None:
        if db_path is None:
            db_path = os.path.join(os.getcwd(), "tracker.fs")
        self.db_path = db_path
        self.trackers = {}
        self.tag_to_id = {}
        self.row_to_id = {}
        self.tag_to_row = {}
        self.id_to_times = {}
        self.active_page = 0
        self.storage = FileStorage.FileStorage(self.db_path)
        self.db = DB(self.storage)
        self.connection = self.db.open()
        self.root = self.connection.root()
        self.next_first = True
        logger.debug(f"using data from\n  {self.db_path}")
        self.load_data()
        self.maybe_backup()

    def load_data(self):
        try:
            if 'settings' not in self.root:
                self.root['settings'] = {}
                self.root['settings']['num_spread'] = 1.5
                self.root['settings']['ampm'] = True
                self.root['settings']['yearfirst'] = True
                self.root['settings']['dayfirst'] = False
                transaction.commit()
            self.settings = self.root['settings']
            if 'trackers' not in self.root:
                self.root['trackers'] = {}
                self.root['next_id'] = 1  # Initialize the ID counter
                transaction.commit()
            self.trackers = self.root['trackers']
        except Exception as e:
            logger.debug(f"Warning: could not load data from '{self.db_path}': {str(e)}")
            self.trackers = {}

    def maybe_backup(self):
        hsh = {}
        for k, v in self.trackers.items():
            f = {}
            f['name'] = v.name
            f['created'] = serialize_record(v.created)
            f['modified'] = serialize_record(v.modifed)
            # _['_info'] = serialize_record(v._info) # can be computed from the other fields
            f['history'] = serialize_record(v.history)

            hsh[k] = f
        logger.debug(f"{hsh = }")
        json_data = json.dumps(hsh, indent=2)
        json_file = os.path.join(os.getcwd(), "tracker.json")
        # Write the data to a JSON file
        # Assuming 'data' is the dictionary you want to dump to a JSON file
        with open(json_file, 'w') as json_file:
            json.dump(hsh, json_file, indent=3, separators=(',', ': '), sort_keys=False)

        # with open(json_file, 'w') as json_file:
        #     json.dump(json_data, json_file, indent=4)
        # logger.debug(f"{self.root['trackers'].items() = }")
        # json_data = {k: serialize_record(v) for k, v in self.root['trackers'].items()}
        # json_file = os.path.join(os.getcwd(), "tracker.json")
        # # Write the data to a JSON file
        # with open(json_file, 'w') as json_file:
        #     json.dump(json_data, json_file, indent=2)

    def set_setting(self, key, value):

        if key in self.settings:
            self.settings[key] = value
            self.zodb_root[0] = self.settings  # Update the ZODB storage
            transaction.commit()
        else:
            print(f"Setting '{key}' not found.")

    def get_setting(self, key):
        return self.settings.get(key, None)

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


    def record_completion(self, doc_id: int, comp: tuple[datetime, timedelta]):
        # dt will be a datetime
        ok, msg = self.trackers[doc_id].record_completion(comp)
        if not ok:
            display_message(msg)
            return
        dt, td = comp
        display_message(f"""\
Recorded completion ({Tracker.format_dt(dt)}, {Tracker.format_td(td)}):\n {self.trackers[doc_id].get_tracker_info()}""", 'info')

    def get_tracker_data(self, doc_id: int = None):
        if doc_id is None:
            logger.debug("data for all trackers:")
            for k, v in self.trackers.items():
                logger.debug(f"   {k:2> }. {v.get_tracker_data()}")
        elif doc_id in self.trackers:
            logger.debug(f"data for tracker {doc_id}:")
            logger.debug(f"   {doc_id:2> }. {self.trackers[doc_id].get_tracker_data()}")

    def sort_key(self, tracker):
        next_dt = tracker._info.get('next_expected_completion', None) if hasattr(tracker, '_info') else None
        last_dt = tracker._info.get('last_completion', None) if hasattr(tracker, '_info') else None
        if self.next_first:
            if next_dt:
                return (0, next_dt)
            if last_dt:
                return (1, last_dt)
            return (2, tracker.doc_id)
        else:
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
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y-%m-%d")
        num_pages = (len(self.trackers) + 25) // 26
        set_pages(page_banner(self.active_page + 1, num_pages))
        banner = f"{ZWNJ} tag     next       last     tracker name\n"
        rows = []
        count = 0
        start_index = self.active_page * 26
        end_index = start_index + 26
        sorted_trackers = self.get_sorted_trackers()
        for tracker in sorted_trackers[start_index:end_index]:
            # logger.debug(f"{tracker.doc_id}: {tracker.name}")
            parts = [x.strip() for x in tracker.name.split('@')]
            tracker_name = parts[0]
            spread = tracker._info.get('spread', None) if hasattr(tracker, '_info') else None
            num_spread = self.get_setting('num_spread')
            next_dt = tracker._info.get('next_expected_completion', None) if hasattr(tracker, '_info') else None
            alert = tracker._info.get('alert', None) if hasattr(tracker, '_info') else None
            warn = tracker._info.get('warn', None) if hasattr(tracker, '_info') else None
            # if num_spread and spread:
            #     alert = (next_dt - num_spread * spread).strftime("%y-%m-%d")
            #     warn = (next_dt + num_spread * spread).strftime("%y-%m-%d")
            # else:
            #     alert = warn = None
            last_completion = tracker._info.get('last_completion', None) if hasattr(tracker, '_info') else None
            last_dt = last_completion[0] if last_completion else None
            next = next_dt.strftime("%y-%m-%d") if next_dt else center_text("~", 8)
            last = last_dt.strftime("%y-%m-%d") if last_dt else center_text("~", 8)
            tag = TrackerManager.labels[count]
            self.id_to_times[tracker.doc_id] = (alert, warn)
            self.tag_to_id[(self.active_page, tag)] = tracker.doc_id
            self.row_to_id[(self.active_page, count+1)] = tracker.doc_id
            self.tag_to_row[(self.active_page, tag)] = count+1
            count += 1
            rows.append(f" {tag}    {next:<8}  {last:<8}  {tracker_name}")
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

    def first_page(self):
        self.set_active_page(0)


    def get_tracker_from_tag(self, tag: str):
        pagetag = (self.active_page, tag)
        if pagetag not in self.tag_to_id:
            return None
        return self.trackers[self.tag_to_id[pagetag]]

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
        tracker = self.get_tracker_from_tag(label)
        if tracker:
            tracker.edit_history()
            self.save_data()
        else:
            logger.debug(f"No tracker found corresponding to label {label}.")

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

db_file = "/Users/dag/track-test/tracker.fs"
json_file = "/Users/dag/track-test/tracker.json"
tracker_manager = TrackerManager(db_file)

tracker_style = {
    'next-warn': 'fg:darkorange',
    'next-alert': 'fg:gold',
    'next-fine': 'fg:lightskyblue',
    'last-less': '',
    'last-more': '',
    'no-dates': '',
    'default': '',
    'banner': 'fg:limegreen',
    'tag': 'fg:gray',
}

banner_regex = re.compile(r'^\u200C')

class DefaultLexer(Lexer):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DefaultLexer, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            now = datetime.now()
        now = datetime.now()

    def lex_document(self, document):
        # Implement the logic for tokenizing the document here.
        # You should yield tuples of (start_pos, Token) pairs for each token in the document.

        # Example: Basic tokenization that highlights keywords in a simple way.
        text = document.text
        for i, line in enumerate(text.splitlines()):
            if "keyword" in line:
                yield i, ('class:keyword', line)
            else:
                yield i, ('', line)


class InfoLexer(Lexer):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(InfoLexer, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            now = datetime.now()
        now = datetime.now()

    def lex_document(self, document):
        # Implement the logic for tokenizing the document here.
        # You should yield tuples of (start_pos, Token) pairs for each token in the document.

        # Example: Basic tokenization that highlights keywords in a simple way.
        logger.debug("lex_document called")
        active_page = tracker_manager.active_page
        lines = document.lines
        now = datetime.now().strftime("%y-%m-%d")
        def get_line_tokens(line_number):
            line = lines[line_number]
            tokens = []
            if line:
                tokens.append((tracker_style.get('default', ''), line))
            return tokens
        return get_line_tokens



class TrackerLexer(Lexer):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TrackerLexer, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            now = datetime.now()
        now = datetime.now()

    def lex_document(self, document):
        # logger.debug("lex_document called")
        active_page = tracker_manager.active_page
        lines = document.lines
        now = datetime.now().strftime("%y-%m-%d")
        def get_line_tokens(line_number):
            line = lines[line_number]
            tokens = []

            if line and line[0] == ' ':  # does line start with a space
                parts = line.split()
                if len(parts) < 4:
                    return [(tracker_style.get('default', ''), line)]

                # Extract the parts of the line
                tag, next_date, last_date, tracker_name = parts[0], parts[1], parts[2], " ".join(parts[3:])
                id = tracker_manager.tag_to_id.get((active_page, tag), None)
                alert, warn = tracker_manager.id_to_times.get(id, (None, None))

                # Determine styles based on dates
                if warn and now >= warn:
                    next_style = tracker_style.get('next-warn', '')
                    last_style = tracker_style.get('next-warn', '')
                    name_style = tracker_style.get('next-warn', '')
                elif alert and now >= alert:
                    next_style = tracker_style.get('next-alert', '')
                    last_style = tracker_style.get('next-alert', '')
                    name_style = tracker_style.get('next-alert', '')
                elif next_date != "~" and next_date > now:
                    next_style = tracker_style.get('next-fine', '')
                    last_style = tracker_style.get('next-fine', '')
                    name_style = tracker_style.get('next-fine', '')
                else:
                    next_style = tracker_style.get('default', '')
                    last_style = tracker_style.get('default', '')
                    name_style = tracker_style.get('default', '')

                # Format each part with fixed width
                tag_formatted = f"  {tag:<5}"          # 7 spaces for tag
                next_formatted = f"{next_date:^8}   "  # 10 spaces for next date
                last_formatted = f"{last_date:^8}   "  # 10 spaces for last date
                # Add the styled parts to the tokens list
                tokens.append((tracker_style.get('tag', ''), tag_formatted))
                tokens.append((next_style, next_formatted))
                tokens.append((last_style, last_formatted))
                tokens.append((name_style, tracker_name))
            elif banner_regex.match(line):
                tokens.append((tracker_style.get('banner', ''), line))
            else:
                tokens.append((tracker_style.get('default', ''), line))
            # logger.debug(f"tokens: {tokens}")
            return tokens

        return get_line_tokens

    @staticmethod
    def _parse_date(date_str):
        return datetime.strptime(date_str, "%y-%m-%d")

def get_lexer(document_type):
    if document_type == 'list':
        return TrackerLexer()
    elif document_type == 'info':
        return InfoLexer()
    else:
        return DefaultLexer()

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
    'message-window': f'bg:#1d3030 {NAMED_COLORS["LimeGreen"]}',
    'status-window': f'bg:#396060 {NAMED_COLORS["White"]}',
})

def check_alarms():
    """Periodic task to check alarms."""
    today = datetime.now().strftime("%y-%m-%d")
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
        newday = ct.strftime("%y-%m-%d")
        if newday != today:
            today = newday

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
bool_mode = [False]
integer_mode = [False]
input_mode = [False]
dialog_visible = [False]
input_visible = [False]
action = [None]

selected_id = None

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

tracker_lexer = TrackerLexer()
info_lexer = InfoLexer()
default_lexer = DefaultLexer()

display_area = TextArea(text="", read_only=True, search_field=search_field, lexer=tracker_lexer)

def set_lexer(document_type: str):
    if document_type == 'list':
        display_area.lexer = tracker_lexer
    elif document_type == 'info':
        display_area.lexer = info_lexer
    else:
        display_area.lexer = default_lexer


# input_area = TextArea(focusable=True, multiline=True, height=2, prompt='> ', style="class:input-area")
input_area = TextArea(
    focusable=True,
    multiline=True,
    prompt='> ',
    height=D(preferred=1, max=5),  # Set preferred and max height
    style="class:input-area"
)

dynamic_input_area = DynamicContainer(lambda: input_area)

dialog_visible = [False]
input_visible = [False]
action = [None]

input_container = ConditionalContainer(
    content=dynamic_input_area,
    filter=Condition(lambda: input_visible[0])
)

message_control = FormattedTextControl(text="")

message_window = DynamicContainer(
    lambda: Window(
        content=message_control,
        height=D(preferred=1, max=3),  # Adjust max height as needed
        style="class:message-window"
    )
)
# message_window = Window(content=message_control, height=2, style="class:message-window")

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

freq = 12

status_control = FormattedTextControl(text=f"{format_statustime(datetime.now(), freq)}")
status_window = Window(content=status_control, height=1, style="class:status-window", width=D(preferred=20), align=WindowAlign.LEFT)

page_control = FormattedTextControl(text="")
page_window = Window(content=page_control, height=1, style="class:status-window", width=D(preferred=20), align=WindowAlign.CENTER)

right_control = FormattedTextControl(text="")
right_window = Window(content=right_control, height=1, style="class:status-window", width=D(preferred=20), align=WindowAlign.RIGHT)
right_control.text = "next/last/neither " if tracker_manager.next_first else "neither/last/next "


def set_pages(txt: str):
    page_control.text = f"{txt} "


status_area = VSplit(
    [
        status_window,
        page_window,
        right_window
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

def set_key_profile(profile: str):
    if profile == 'menu':
        # for selecting menu items with a key press
        menu_mode[0] = True
        select_mode[0] = False
        bool_mode[0] = False
        integer_mode[0] = False
        dialog_visible[0] = False
        input_visible[0] = False
    elif profile == 'select':
        # for selecting rows by a lower case letter key press
        menu_mode[0] = False
        select_mode[0] = True
        bool_mode[0] = False
        integer_mode[0] = False
        dialog_visible[0] = True
        input_visible[0] = False
    elif profile == 'bool':
        # for selecting y/n with a key press
        menu_mode[0] = False
        select_mode[0] = False
        bool_mode[0] = True
        integer_mode[0] = False
        dialog_visible[0] = True
        input_visible[0] = False
    elif profile == 'integer':
        # for selecting an single digit integer with a key press
        menu_mode[0] = False
        select_mode[0] = False
        bool_mode[0] = False
        integer_mode[0] = True
        dialog_visible[0] = True
        input_visible[0] = False
    elif profile == 'input':
        # for entering text in the input area
        menu_mode[0] = False
        select_mode[0] = False
        bool_mode[0] = False
        integer_mode[0] = False
        dialog_visible[0] = True
        input_visible[0] = True



key_msg = "press the key corresponding to the tag of the tracker"
labels = "abcdefghijklmnopqrstuvwxyz"

tag_keys = list(string.ascii_lowercase)
tag_keys.append('escape')

def get_key_press(event):
    key_pressed = event.key_sequence[0].key
    logger.debug(f"got key: {key_pressed}; action: '{action[0]}'")
    return key_pressed

def handle_key(event, key):
    result['key'] = key
    # Remove the prompt from the layout
    # root_container.children.remove(prompt_window)
    # event.app.layout.focus(root_container.children[0])  # Restore focus
    event.app.exit(result=result)

# from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application.current import get_app

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application.current import get_app

def get_yes_no(message):
    result['key'] = 'n'

    @kb.add('escape')
    def handle_escape(event):
        result['key'] = 'escape'

    # Temporarily set the key bindings
    app = get_app()
    previous_key_bindings = app.key_bindings
    app.key_bindings = kb

    # Run the event loop and wait for the key press
    app.run()  # This should now be used in a synchronous manner within the loop

    # Restore the original key bindings
    app.key_bindings = previous_key_bindings

    # Return the key pressed
    return result['key']


# @kb.add('y', 'n', filter=Condition(lambda: bool_mode[0] == True))
# def get_bool(event):
#     key_pressed = event.key_sequence[0].key
#     logger.debug(f"got key: {key_pressed}; action: '{action[0]}'")
#     return key_pressed == 'y'


# @kb.add(*list(labels), filter=Condition(lambda: select_mode[0]))
def get_selection(event):
    global selected_id
    key_pressed = event.key_sequence[0].key
    logger.debug(f"got key: {key_pressed}; action: '{action[0]}'")
    if key_pressed in labels:
        selected_id = tracker_manager.get_id_from_label(key_pressed)
        set_key_profile('menu')
        list_trackers()



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

def display_message(message: str, document_type: str = 'list'):
    """Log messages to the text area."""
    set_lexer(document_type)
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
    display_message(tracker_manager.list_trackers(), 'list')
    # message_control.text = "Adding a new tracker..."
    app.layout.focus(display_area)
    app.invalidate()

@kb.add('t', filter=Condition(lambda: menu_mode[0]))
def jump_to_tag(*event):
    pass


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

@kb.add('space', filter=Condition(lambda: menu_mode[0]))
def first_page(*event):
    logger.debug("first page")
    tracker_manager.first_page()
    list_trackers()

@kb.add('r', filter=Condition(lambda: menu_mode[0]))
def reverse_sort(*event):
    tracker_manager.next_first = not tracker_manager.next_first
    right_control.text = "next/last/neither " if tracker_manager.next_first else "neither/last/next "
    # right_control.text = "next first " if tracker_manager.next_first else "next last "
    list_trackers()

@kb.add('t', filter=Condition(lambda: menu_mode[0]))
def select_tag(*event):
    """
    From a keypress corresponding to a tag, move the cursor to the row corresponding to the tag and set the selected_id to the id of the corresponding tracker.
    """
    global done_keys, selected_id
    done_keys = tag_keys
    message_control.text = key_msg
    set_key_profile('select')

    for key in tag_keys:
        kb.add(key, filter=Condition(lambda: select_mode[0]), eager=True)(lambda event, key=key: handle_key_press(event, key))

    def handle_key_press(event, key):
        key_pressed = event.key_sequence[0].key
        logger.debug(f"{tracker_manager.tag_to_row = }")
        if key_pressed in done_keys:
            set_key_profile('menu')
            message_control.text = ""
            if key_pressed == 'escape':
                return

            tag = (tracker_manager.active_page, key_pressed)
            selected_id = tracker_manager.tag_to_id.get(tag)
            row = tracker_manager.tag_to_row.get(tag)
            logger.debug(f"got id {selected_id} and row {row} from tag {key_pressed}")
            display_area.buffer.cursor_position = (
                display_area.buffer.document.translate_row_col_to_index(row, 0)
            )

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
    global done_keys, selected_id
    tracker = get_tracker_from_row()
    logger.debug(f"in tracker_info: {tracker = }")
    action[0] = "info"
    if tracker:
        logger.debug("got tracker from row, calling process_tracker")
        set_key_profile('menu')
        display_message(tracker.get_tracker_info(), 'info')
        app.layout.focus(display_area)
        return
        # message_control.text = key_msg
    done_keys = tag_keys
    message_control.text = key_msg
    set_key_profile('select')

    for key in tag_keys:
        kb.add(key, filter=Condition(lambda: select_mode[0]), eager=True)(lambda event, key=key: handle_key_press(event, key))

    def handle_key_press(event, key):
        key_pressed = event.key_sequence[0].key
        logger.debug(f"{tracker_manager.tag_to_row = }")
        if key_pressed in done_keys:
            set_key_profile('menu')
            message_control.text = ""
            if key_pressed == 'escape':
                return

            tag = (tracker_manager.active_page, key_pressed)
            selected_id = tracker_manager.tag_to_id.get(tag)
            tracker = tracker_manager.get_tracker_from_id(selected_id)
            logger.debug(f"got id {selected_id} and tracker {tracker} from tag {tag}")
            display_message(tracker.get_tracker_info(), 'info')
            app.layout.focus(display_area)


@kb.add('n', filter=Condition(lambda: menu_mode[0]))
def new_tracker(*event):
    """Add a new tracker."""
    action[0] = "new"
    menu_mode[0] = False
    select_mode[0] = False
    dialog_visible[0] = True
    input_visible[0] = True
    message_control.text = wrap(" Enter the name for the new tracker. Append @ followed by an integer number of days to flag this tracker when this number of days has passed since the last completion.", 0)
    logger.debug(f"action: {action[0]} getting tracker name ...")
    app.layout.focus(input_area)

    input_area.accept_handler = lambda buffer: handle_input()

    @kb.add('c-s', filter=Condition(lambda: action[0]=="new"))
    def handle_input(event):
        """Handle input when Enter is pressed."""
        parts = [x.strip() for x in input_area.text.split()]
        tracker_name = parts[0]
        if tracker_name:
            logger.debug(f"got tracker name: {tracker_name}")
            tracker_manager.add_tracker(
                name=tracker_name,
                )
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
    global done_keys, selected_id
    tracker = get_tracker_from_row()
    logger.debug(f"in add_completion: {tracker = }")
    action[0] = "complete"
    if tracker:
        selected_id = tracker.doc_id
        logger.debug("got tracker from row, calling process_tracker")
        set_key_profile('input')
        message_control.text = f"Enter the new completion datetime for {tracker.name} (doc_id: {selected_id})"
        app.layout.focus(input_area)
        input_area.accept_handler = lambda buffer: handle_completion()
        return

    done_keys = tag_keys
    message_control.text = key_msg
    set_key_profile('select')

    for key in tag_keys:
        kb.add(key, filter=Condition(lambda: select_mode[0]), eager=True)(lambda event, key=key: handle_key_press(event, key))

    def handle_key_press(event, key):
        global selected_id
        key_pressed = event.key_sequence[0].key
        logger.debug(f"{tracker_manager.tag_to_row = }")
        if key_pressed in done_keys:
            if key_pressed == 'escape':
                return
            tag = (tracker_manager.active_page, key_pressed)
            selected_id = tracker_manager.tag_to_id.get(tag)
            tracker = tracker_manager.get_tracker_from_id(selected_id)
            logger.debug(f"got id {selected_id} from tag {tag}")
            set_key_profile('input')
            message_control.text = f"Enter the new completion datetime for {tracker.name} ({selected_id})"
            app.layout.focus(input_area)
            input_area.accept_handler = lambda buffer: handle_completion()



        # logger.debug("using label selection")
        # menu_mode[0] = False
        # select_mode[0] = True
        # dialog_visible[0] = True
        # input_visible[0] = False
        # message_control.text = f"{key_msg} add completion."

@kb.add('c-s', filter=Condition(lambda: action[0]=="complete"))
def handle_completion(event):
    """Handle input when Enter is pressed."""
    menu_mode[0] = False
    completion_str = input_area.text.strip()
    logger.debug(f"got completion_str: '{completion_str}' for {selected_id}")
    if completion_str:
        ok, completion = Tracker.parse_completion(completion_str)
        logger.debug(f"recording completion_dt: '{completion}' for {selected_id}")
        tracker_manager.record_completion(selected_id, completion)
        close_dialog()
    else:
        display_area.text = "No completion datetime provided."
    # app.layout.focus(display_area)


@kb.add('d', filter=Condition(lambda: menu_mode[0]))
def delete_tracker(*event):
    """Delete a tracker."""
    global selected_id
    action[0] = "delete"
    logger.debug(f"action: '{action[0]}'")
    tracker = get_tracker_from_row()
    if not tracker:
        logger.debug("using label selection")
        set_key_profile('select')
        tracker = tracker_manager.get_tracker_from_tag(key)
    if tracker:
        selected_id = tracker.doc_id
        logger.debug("got tracker from row, calling process_tracker")
        # process_tracker(event, tracker)
    else:
        pass
        # message_control.text = f"{key_msg} delete."
    result = get_yes_no("Are you sure you want to delete this tracker?  yN")
    if result['key'] == 'y':
        tracker_manager.delete_tracker(selected_id)
        message_control.text = f"Deleted tracker {selected_id}"
    else:
        message_control.text = f"Cancelled deletion"
    list_trackers()
    # set_key_profile('bool')
    # logger.debug(f"bool_mode: {bool_mode[0]}")
    # input_area.text = ""
    # message_control.text = "Are you sure you want to delete this tracker?  yN"

    # @kb.add('y', 'n', filter=Condition(lambda: bool_mode[0] == True))
    # def handle_key(event):
    #     key_pressed = event.key_sequence[0].key
    #     logger.debug(f"got key: {key_pressed}; action: '{action[0]}'")
    #     if key_pressed == 'y':
    #         tracker_manager.delete_tracker(selected_id)
    #         message_control.text = f"Deleted tracker {selected_id}"
    #     else:
    #         message_control.text = f"Cancelled deletion"
    #     set_key_profile('menu')
    #     list_trackers()

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

selected_id = None

def get_tracker():
    global selected_id

def select_tracker_from_label(event, key: str):
    """Generic tracker selection."""
    global selected_id
    message_control.text = "Press the key of tag for the tracker you want to select."
    tracker = tracker_manager.get_tracker_from_tag(key)
    if tracker:
        row = tracker_manager.tag_to_row.get(key)
        logger.debug(f"got row {row} from tag {key}")
        selected_id = tracker.doc_id
        select_mode[0] = False
        display_area.buffer.cursor_position = (
            display_area.buffer.document.translate_row_col_to_index(row, 0)
        )


confirmation = False
confirm_command = None
def process_tracker(event, tracker: Tracker = None):
    global selected_id, confirm_command
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
            if input_area.text == "n":
                list_trackers()
                return
            select_mode[0] = False
            dialog_visible[0] = True
            input_visible[0] = False
            # app.layout.focus(input_area)
            tracker_manager.delete_tracker(selected_id)
            list_trackers()
            # confirmation = get_confirmation(message=message)
            # logger.debug(f"got confirmation: {confirmation = }")
            # if confirmation == True:
            #     tracker_manager.delete_tracker(selected_id)
            # else:
            #     display_area.text = "Deletion cancelled."

        elif action[0] == "complete":
            message_control.text = f"Enter the new completion datetime for {tracker.name} ({selected_id})"
            # logger.debug(f"Entering the new completion datetime for {tracker.name} ({selected_id})")
            select_mode[0] = False
            dialog_visible[0] = True
            input_visible[0] = True
            app.layout.focus(input_area)
            input_area.accept_handler = lambda buffer: handle_completion()
        elif action[0] == "info":
            select_mode[0] = False
            dialog_visible[0] = False
            input_visible[0] = False
            # info = tracker.get_tracker_info()
            # logger.debug(f"{info = }")
            display_message(tracker.get_tracker_info(), 'info')
            app.layout.focus(display_area)
        app.invalidate()
    else:
        list_trackers()

# Bind all lowercase letters to select_tracker
# keys = list(string.ascii_lowercase)
# keys.append('escape')
# for key in keys:
#     kb.add(key, filter=Condition(lambda: select_mode[0]), eager=True)(lambda event, key=key: select_tracker_from_label(event, key))

# Layout

# @kb.add('y', filter=Condition(lambda: input_visible[0]))
# def yes(event):
#     action[0] = True
#     input_visible[0] = False
#     dialog_visible[0] = False

# @kb.add('n', filter=Condition(lambda: input_visible[0]))
# def no(event):
#     action[0] = False
#     input_visible[0] = False
#     dialog_visible[0] = False

# Method to get confirmation
# def get_confirmation(message: str) -> bool:
#     # Display the message
#     message_control.text = message

#     # Show the dialog and input area
#     dialog_visible[0] = True
#     input_visible[0] = True

#     # Create an application instance
#     app = Application(
#         layout=layout,
#         key_bindings=kb,
#         full_screen=True,
#     )

#     # Run the application (this will block until the app exits)
#     app.run()

#     # Return the action taken by the user (True for 'y', False for 'n')
#     return action[0]

# def confirm_command(message: str)-> bool:
#     message_control.text = message
#     # dialog_visible[0] = True
#     # input_visible[0] = True
#     app.layout.focus(input_area)
#     input_area.accept_handler = lambda buffer: handle_confirmation()


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
                MenuItem('i) tracker info', handler=tracker_info),
                MenuItem('l) list trackers', handler=list_trackers),
                MenuItem('r) reverse sort', handler=reverse_sort),
                MenuItem('t) select tag', handler=select_tag),
            ]
        ),
    ]
)

layout = Layout(root_container)
# app = Application(layout=layout, key_bindings=kb, full_screen=True, style=style)

app = Application(layout=layout, key_bindings=kb, full_screen=True, mouse_support=True, style=style)

app.layout.focus(root_container.body)


def main():
    # global tracker_manager
    try:
        # TODO: use an environment variable or ~/.tracker/tracker.fs?
        logging.info(f"Started TrackerManager with database file {db_file}")

        display_text = tracker_manager.list_trackers()
        # logging.debug(f"Tracker list: {display_text}")
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
