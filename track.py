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
    HorizontalLine,
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
from logging.handlers import TimedRotatingFileHandler

from ZODB import DB, FileStorage
from persistent import Persistent
import transaction
import os
import time
import json
from io import StringIO

import textwrap
import re
import __version__ as version

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

def clear_screen():
    # For Windows
    if os.name == 'nt':
        os.system('cls')
    # For macOS and Linux (posix systems)
    else:
        os.system('clear')

# Initialize YAML object
yaml = YAML()

# Create a CommentedMap, which behaves like a Python dictionary but supports comments
settings_map = CommentedMap({
    'ampm': True,
    'yearfirst': True,
    'dayfirst': False,
    'σ': 2
})
# Add comments to the dictionary
settings_map.yaml_set_comment_before_after_key('ampm', before='Track Settings\n\n[ampm] Display 12-hour times with AM or PM if true, \notherwise display 24-hour times')
settings_map.yaml_set_comment_before_after_key('yearfirst', before='\n[yearfirst] When parsing ambiguous dates, assume the year is first if true, \notherwise assume the month is first')
settings_map.yaml_set_comment_before_after_key('dayfirst', before='\n[dayfirst] When parsing ambiguous dates, assume the day is first if true, \notherwise assume the month is first')
settings_map.yaml_set_comment_before_after_key('σ', before='\n[σ] Use this integer multiple of "spread" for setting the early-to-late \nforecast confidence interval')


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

# Backup and restore
import zipfile

# Specify the files to include in the backup
# FIXME: just a first paso
def backup_to_zip(track_home, today):
    backup_dir = os.path.join(track_home, 'backup')
    files_to_backup = [os.path.join(track_home, 'track.fs'), os.path.join(track_home, 'track.fs.index')]

    for file in files_to_backup:
        if not os.path.exists(file):
            return (False, f"Cancelled - {file} does not exist")

    if today == 'remove':
        files_to_backup +=  [os.path.join(track_home, 'track.fs.tmp'), os.path.join(track_home, 'track.fs.lock')]
        backup_zip = os.path.join(track_home, 'backup', f"removed.zip")
    else:
        # files_to_backup = [os.path.join(track_home, 'track.fs'), os.path.join(track_home, 'track.fs.index')]
        backup_zip = os.path.join(track_home, 'backup', f"{today.strftime('%y%m%d')}.zip")
        if os.path.exists(backup_zip):
            return (False, f"Cancelled - backup already exists: {backup_zip}")

    # print(f"backing up: {backup_dir = }, {files_to_backup = }, backup_zip = {backup_zip = }")

    # Create a zip file and add the files
    with zipfile.ZipFile(backup_zip, 'w') as zipf:
        for file in files_to_backup:
            zipf.write(file)


    if today == 'remove':
        for fp in files_to_backup:
            if os.path.exists(fp):
                os.remove(fp)
        return (True, f"Backup completed and original files removed. ")

    return (True, f"Backup completed: {backup_zip}")


def rotate_backups(backup_dir):
    today = datetime.today()
    ok, msg = backup_to_zip(track_home, today)
    if not ok:
        logger.info(msg)
        return

    # List all files in the backup directory
    pattern = re.compile(r'^\d{6}\.zip$')
    all_files = os.listdir(backup_dir)
    # Filter the files matching the regex pattern
    files = [f for f in all_files if pattern.match(f)]
    names = [os.path.splitext(f)[0] for f in all_files if pattern.match(f)]
    daily = []
    recent = []
    medium = []
    old = []
    rlim = (today - timedelta(days=18)).strftime("%y%m%d")
    mlim = (today - timedelta(days=32)).strftime("%y%m%d")
    olim = (today - timedelta(days=46)).strftime("%y%m%d")

    names.sort()
    for name in names:
        remove = []
        if name > rlim:
            daily.append(name)
        elif name > mlim:
            recent.append(name)
        elif name > olim:
            medium.append(name)
        else:
            old.append(name)

        if len(daily) > 3:
            m = daily.pop(0)
            recent.append(m)
        if len(recent) > 1:
            if recent[0] < rlim:
                r = recent.pop(0)
                medium.append(r)
            else:
                r = recent.pop(-1)
                remove.append(r)
        if len(medium) > 1:
            if medium[0] < mlim:
                m = medium.pop(0)
                old.append(m)
            else:
                m = medium.pop(-1)
                remove.append(m)
        if len(old) > 1:
            if old[0] < olim:
                o = old.pop(0)
                remove.append(o)

        for r in remove:
            fp = os.path.join(backup_dir, f"{r}.zip")
            if os.path.exists(fp):
                os.remove(fp)
                print(f"removed {fp}")
                names.remove(r)

# FIXME: just a first pass
def restore_from_zip(track_home):
    clear_screen()
    backup_dir = os.path.join(track_home, 'backup')
    print(f"""
 Choosing one of the 'restore from' options listed below will

    1) compress all track.fs* files in {track_home} into "remove.zip"
       in {backup_dir}, overwriting "remove.zip" if it exists

    2) remove all track.fs* files from {track_home}

    3) restore the files "track.fs" and "track.fs.index" from the
       selected zip file into {track_home}

 Note: The file "remove.zip" will be overwritten by any subsequent
 restore operation.

 WARNING: Choosing an option other than "0: cancel" CANNOT BE UNDONE.
""")
    pattern = re.compile(r'^\d{6}\.zip$')
    all_files = os.listdir(backup_dir)
    names = [os.path.splitext(f)[0] for f in all_files if pattern.match(f)]
    names.sort(reverse=True)

    restore_options = {'0': 'cancel'}
    for i, name in enumerate(names, 1):
        restore_options[str(i)] = name

    while True:
        print(" Options:")
        for opt, value in restore_options.items():
            print(f"    {opt}: restore from '{value}'" if opt != '0' else f"    {opt}: {restore_options[opt]}")

        choice = input("Choose an option: ").strip().lower()
        if choice in restore_options:
            if choice == '0':
                print("Restore cancelled.")
                sys.exit()
            #  we have a valid restore option
            # Extract the files
            ok, msg = backup_to_zip(track_home, 'remove')
            print(msg)
            chosen_name = restore_options[choice]
            backup_zip = os.path.join(backup_dir, chosen_name + '.zip')
            print(f"Extracting files from {backup_zip}")

            with zipfile.ZipFile(backup_zip, 'r') as zipf:
                zipf.extractall()
            sys.exit()

        else:
            print("Invalid option. Please choose again.")



def setup_logging():
    """
    Set up logging with daily rotation and a specified log level.

    Args:
        logfile (str): The file where logs will be written.
        log_level (int): The log level (e.g., logging.DEBUG, logging.INFO).
        backup_count (int): Number of backup log files to keep.
    """
    backup_count = 7
    log_level = logging.INFO

    if len(sys.argv) > 1:
        try:
            log_level = int(sys.argv[1])
            sys.argv.pop(1)
        except ValueError:
            print(f"Invalid log level: {sys.argv[1]}. Using default INFO level.")

    envhome = os.environ.get('TRACKHOME')
    if len(sys.argv) > 1:
        trackhome = sys.argv[1]
    elif envhome:
        trackhome = envhome
    else:
        trackhome = os.getcwd()

    restore = len(sys.argv) > 2 and sys.argv[2] == 'restore'

    if restore:
        # backup_dir = os.path.join(trackhome, 'backup')
        restore_from_zip(trackhome)
        sys.exit()


    logfile = os.path.join(trackhome, "logs", "track.log")

    # Create a TimedRotatingFileHandler for daily log rotation
    handler = TimedRotatingFileHandler(
        logfile, when="midnight", interval=1, backupCount=backup_count
    )

    # Set the suffix to add the date and ".log" extension to the rotated files
    handler.suffix = "%y%m%d.log"

    # Create a formatter
    formatter = logging.Formatter(
        fmt='--- %(asctime)s - %(levelname)s - %(module)s.%(funcName)s\n    %(message)s',
        datefmt="%y-%m-%d %H:%M:%S"
    )

    # Set the formatter to the handler
    handler.setFormatter(formatter)

    # Define a custom namer function to change the log file naming format
    def custom_namer(filename):
        # Replace "tracker.log." with "tracker-" in the rotated log filename
        return filename.replace("track.log.", "track")

    # Set the handler's namer function
    handler.namer = custom_namer

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Clear any existing handlers (if needed)
    if logger.hasHandlers():
        logger.handlers.clear()

    # Add the TimedRotatingFileHandler to the logger
    logger.addHandler(handler)

    logger.info("Logging setup complete.")
    logging.info(f"\n### Logging initialized at level {log_level} ###")

    return trackhome

# make logging available globally
track_home = setup_logging()
logger = logging.getLogger()
logger.info(f"track version: {version.version}; track_home: {track_home}")


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
    def format_dt(cls, dt: Any, long=False) -> str:
        if not isinstance(dt, datetime):
            return ""
        if long:
            return dt.strftime("%Y-%m-%d %H:%M")
        return dt.strftime("%y%m%dT%H%M")

    @classmethod
    def td2seconds(cls, td: timedelta) -> str:
        if not isinstance(td, timedelta):
            return ""
        return f"{round(td.total_seconds())}"

    @classmethod
    def format_td(cls, td: timedelta, short=False):
        if not isinstance(td, timedelta):
            return None
        sign = '+' if td.total_seconds() >= 0 else '-'
        total_seconds = abs(int(td.total_seconds()))
        if total_seconds == 0:
            # return '0 minutes '
            return '0m' if short else '+0m'
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
                until.append(f'{days}d')
            if hours:
                until.append(f'{hours}h')
            if minutes:
                until.append(f'{minutes}m')
            if not until:
                until.append('0m')
            ret = ''.join(until[:2]) if short else sign + ''.join(until)
            return ret
        except Exception as e:
            logger.debug(f'{td}: {e}')
            return ''

    @classmethod
    def format_completion(cls, completion: tuple[datetime, timedelta], long=False)->str:
        dt, td = completion
        return f"{cls.format_dt(dt, long=True)}, {cls.format_td(td)}"

    @classmethod
    def parse_td(cls, td:str)->tuple[bool, timedelta]:
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
            m = expanded_period_regex.findall(str(td))
            if not m:
                return False, f"Invalid period string '{td}'"
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

    @classmethod
    def parse_completions(cls, completions: List[str]) -> List[tuple[datetime, timedelta]]:
        completions = [x.strip() for x in completions.split('; ') if x.strip()]
        output = []
        msg = []
        for completion in completions:
            ok, x = cls.parse_completion(completion)
            if ok:
                output.append(x)
            else:
                msg.append(x)
        if msg:
            return False, "; ".join(msg)
        return True, output


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
        if not self.history:
            result = dict(
                last_completion=None, num_completions=0, num_intervals=0, average_interval=timedelta(minutes=0), last_interval=timedelta(minutes=0), spread=timedelta(minutes=0), next_expected_completion=None,
                early=None, late=None, avg=None
                )
        else:
            result['last_completion'] = self.history[-1] if len(self.history) > 0 else None
            result['num_completions'] = len(self.history)
            result['intervals'] = []
            result['num_intervals'] = 0
            result['spread'] = timedelta(minutes=0)
            result['last_interval'] = None
            result['average_interval'] = None
            result['next_expected_completion'] = None
            result['early'] = None
            result['late'] = None
            result['avg'] = None
            if result['num_completions'] > 0:
                for i in range(len(self.history)-1):
                    #                      x[i+1]                  y[i+1]               x[i]
                    logger.debug(f"{self.history[i+1]}")
                    result['intervals'].append(self.history[i+1][0] + self.history[i+1][1] - self.history[i][0])
                result['num_intervals'] = len(result['intervals'])
            if result['num_intervals'] > 0:
                # result['last_interval'] = intervals[-1]
                if result['num_intervals'] == 1:
                    result['average_interval'] = result['intervals'][-1]
                else:
                    result['average_interval'] = sum(result['intervals'], timedelta()) / result['num_intervals']
                result['next_expected_completion'] = result['last_completion'][0] + result['average_interval']
                result['early'] = result['next_expected_completion'] - timedelta(days=1)
                result['late'] = result['next_expected_completion'] + timedelta(days=1)
                change = result['intervals'][-1] - result['average_interval']
                direction = "↑" if change > timedelta(0) else "↓" if change < timedelta(0) else "→"
                result['avg'] = f"{Tracker.format_td(result['average_interval'], True)}{direction}"
                logger.debug(f"{result['avg'] = }")
            if result['num_intervals'] >= 2:
                total = timedelta(minutes=0)
                for interval in result['intervals']:
                    if interval < result['average_interval']:
                        total += result['average_interval'] - interval
                    else:
                        total += interval - result['average_interval']
                result['spread'] = total / result['num_intervals']
            if result['num_intervals'] >= 1:
                result['early'] = result['next_expected_completion'] - tracker_manager.settings['σ'] * result['spread']
                result['late'] = result['next_expected_completion'] + tracker_manager.settings['σ'] * result['spread']

        self._info = result
        self._p_changed = True
        # logger.debug(f"returning {result = }")

        return result

    # XXX: Just for reference
    def add_to_history(self, new_event):
        self.history.append(new_event)
        self.modifed = datetime.now()
        self.invalidate_info()
        self._p_changed = True  # Mark object as changed in ZODB

    def format_history(self)->str:
        output = []
        for completion in self.history:
            output.append(Tracker.format_completion(completion, long=True))
        return '; '.join(output)

    def invalidate_info(self):
        # Invalidate the cached dict so it will be recomputed on next access
        if hasattr(self, '_info'):
            delattr(self, '_info')
        self.compute_info()


    def record_completion(self, completion: tuple[datetime, timedelta]):
        ok, msg = True, ""
        if not isinstance(completion, tuple) or len(completion) < 2:
            completion = (completion, timedelta(0))
        self.history.append(completion)
        self.history.sort(key=lambda x: x[0])
        if len(self.history) > Tracker.max_history:
            self.history = self.history[-Tracker.max_history:]

        # Notify ZODB that this object has changed
        self.invalidate_info()
        self.modifed = datetime.now()
        self._p_changed = True
        return True, f"recorded completion for ..."

    def rename(self, name: str):
        self.name = name
        self.invalidate_info()
        self.modifed = datetime.now()
        self._p_changed = True

    def record_completions(self, completions: list[tuple[datetime, timedelta]]):
        logger.debug(f"starting {self.history = }")
        self.history = []
        for completion in completions:
            if not isinstance(completion, tuple) or len(completion) < 2:
                completion = (completion, timedelta(0))
            self.history.append(completion)
        self.history.sort(key=lambda x: x[0])
        if len(self.history) > Tracker.max_history:
            self.history = self.history[-Tracker.max_history:]
        logger.debug(f"ending {self.history = }")
        self.invalidate_info()
        self.modifed = datetime.now()
        self._p_changed = True
        return True, f"recorded completions for ..."


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
        logger.debug(f"{self._info = }")
        logger.debug(f"{self._info['avg'] = }")
        # insert a placeholder to prevent date and time from being split across multiple lines when wrapping
        # format_str = f"%y-%m-%d{PLACEHOLDER}%H:%M"
        logger.debug(f"{self.history = }")
        history = [f"{Tracker.format_dt(x[0])} {Tracker.format_td(x[1])}" for x in self.history]
        history = ', '.join(history)
        intervals = [f"{Tracker.format_td(x)}" for x in self._info['intervals']]
        intervals = ', '.join(intervals)
        return wrap(f"""\
 name:        {self.name}
 doc_id:      {self.doc_id}
 created:     {Tracker.format_dt(self.created)}
 modified:    {Tracker.format_dt(self.modifed)}
 completions: ({self._info['num_completions']})
    {history}
 intervals:   ({self._info['num_intervals']})
    {intervals}
    average:  {self._info['avg']}
    spread:   {Tracker.format_td(self._info['spread'], True)}
 forecast:    {Tracker.format_dt(self._info['next_expected_completion'])}
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
        self.sort_by = "forecast"  # default sort order, also "latest", "name"
        logger.debug(f"using data from\n  {self.db_path}")
        self.load_data()

    def load_data(self):
        try:
            if 'settings' not in self.root:
                self.root['settings'] = settings_map
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

    def restore_defaults(self):
        self.root['settings'] = settings_map
        self.settings = self.root['settings']
        transaction.commit()
        logger.info(f"Restored default settings:\n{self.settings}")
        self.refresh_info()

    def refresh_info(self):
        for k, v in self.trackers.items():
            v.compute_info()
        logger.info("Refreshed tracker info.")

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
        return doc_id


    def record_completion(self, doc_id: int, comp: tuple[datetime, timedelta]):
        # dt will be a datetime
        ok, msg = self.trackers[doc_id].record_completion(comp)
        if not ok:
            display_message(msg)
            return
        # self.trackers[doc_id].compute_info()
        display_message(f"{self.trackers[doc_id].get_tracker_info()}", 'info')

    def record_completions(self, doc_id: int, completions: list[tuple[datetime, timedelta]]):
        ok, msg = self.trackers[doc_id].record_completions(completions)
        if not ok:
            display_message(msg, 'error')
            return
        display_message(f"{self.trackers[doc_id].get_tracker_info()}", 'info')


    def get_tracker_data(self, doc_id: int = None):
        if doc_id is None:
            logger.debug("data for all trackers:")
            for k, v in self.trackers.items():
                logger.debug(f"   {k:2> }. {v.get_tracker_data()}")
        elif doc_id in self.trackers:
            logger.debug(f"data for tracker {doc_id}:")
            logger.debug(f"   {doc_id:2> }. {self.trackers[doc_id].get_tracker_data()}")

    def sort_key(self, tracker):
        forecast_dt = tracker._info.get('next_expected_completion', None) if hasattr(tracker, '_info') else None
        latest_dt = tracker._info.get('last_completion', None) if hasattr(tracker, '_info') else None
        if self.sort_by == "forecast":
            if forecast_dt:
                return (0, forecast_dt)
            if latest_dt:
                return (1, latest_dt)
            return (2, tracker.doc_id)
        if self.sort_by == "latest":
            if latest_dt:
                return (1, latest_dt)
            if forecast_dt:
                return (2, forecast_dt)
            return (0, tracker.doc_id)
        elif self.sort_by == "name":
            return (0, tracker.name)
        elif self.sort_by == "id":
            return (0, tracker.doc_id)
        else: # forecast
            if forecast_dt:
                return (0, forecast_dt)
            if latest_dt:
                return (1, latest_dt)
            return (2, tracker.doc_id)

    def get_sorted_trackers(self):
        # Extract the list of trackers
        trackers = [v for k, v in self.trackers.items()]
        # Sort the trackers
        return sorted(trackers, key=self.sort_key)

    def list_trackers(self):
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y-%m-%d")
        # width = shutil.get_terminal_size()[0]
        name_width = shutil.get_terminal_size()[0] - 30
        num_pages = (len(self.trackers) + 25) // 26
        set_pages(page_banner(self.active_page + 1, num_pages))
        banner = f"{ZWNJ} tag   forecast  σ spread   latest   name\n"
        rows = []
        count = 0
        start_index = self.active_page * 26
        end_index = start_index + 26
        sorted_trackers = self.get_sorted_trackers()
        sigma = self.settings.get('σ', 1)
        for tracker in sorted_trackers[start_index:end_index]:
            parts = [x.strip() for x in tracker.name.split('@')]
            tracker_name = parts[0]
            if len(tracker_name) > name_width:
                tracker_name = tracker_name[:name_width - 1] + "…"
            forecast_dt = tracker._info.get('next_expected_completion', None) if hasattr(tracker, '_info') else None
            early = tracker._info.get('early', '') if hasattr(tracker, '_info') else ''
            late = tracker._info.get('late', '') if hasattr(tracker, '_info') else ''
            spread = tracker._info.get('spread', '') if hasattr(tracker, '_info') else ''
            # spread = f"±{Tracker.format_td(spread)[1:]: <8}" if spread else f"{'~': ^8}"
            spread = f"{Tracker.format_td(sigma*spread)[1:]: <8}" if spread else f"{'~': ^8}"
            if tracker.history:
                latest = tracker.history[-1][0].strftime("%y-%m-%d")
            else:
                latest = "~"
            forecast = forecast_dt.strftime("%y-%m-%d") if forecast_dt else center_text("~", 8)
            avg = tracker._info.get('avg', None) if hasattr(tracker, '_info') else None
            interval = f"{avg: <8}" if avg else f"{'~': ^8}"
            tag = TrackerManager.labels[count]
            self.id_to_times[tracker.doc_id] = (early.strftime("%y-%m-%d") if early else '', late.strftime("%y-%m-%d") if late else '')
            self.tag_to_id[(self.active_page, tag)] = tracker.doc_id
            self.row_to_id[(self.active_page, count+1)] = tracker.doc_id
            self.tag_to_row[(self.active_page, tag)] = count+1
            count += 1
            # rows.append(f" {tag}{" "*4}{forecast}{" "*2}{latest}{" "*2}{interval}{" " * 3}{tracker_name}")
            rows.append(f" {tag}{" "*4}{forecast}{" "*2}{spread}{" "*2}{latest}{" " * 3}{tracker_name}")
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

db_file = os.path.join(track_home, "track.fs")
backup_dir = os.path.join(track_home, "backup")
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


class HelpLexer(Lexer):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(HelpLexer, cls).__new__(cls, *args, **kwargs)
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
                tag, next_date, spread, last_date, tracker_name = parts[0], parts[1], parts[2], parts[3], " ".join(parts[4:])
                id = tracker_manager.tag_to_id.get((active_page, tag), None)
                alert, warn = tracker_manager.id_to_times.get(id, (None, None))

                # Determine styles based on dates
                if alert and warn:
                    if now < alert:
                        # logger.debug("fine")
                        next_style = tracker_style.get('next-fine', '')
                        last_style = tracker_style.get('next-fine', '')
                        spread_style = tracker_style.get('next-fine', '')
                        name_style = tracker_style.get('next-fine', '')
                    elif now >= alert and now < warn:
                        # logger.debug("alert")
                        next_style = tracker_style.get('next-alert', '')
                        last_style = tracker_style.get('next-alert', '')
                        spread_style = tracker_style.get('next-alert', '')
                        name_style = tracker_style.get('next-alert', '')
                    elif now >= warn:
                        # logger.debug("warn")
                        next_style = tracker_style.get('next-warn', '')
                        last_style = tracker_style.get('next-warn', '')
                        spread_style = tracker_style.get('next-warn', '')
                        name_style = tracker_style.get('next-warn', '')
                elif next_date != "~" and next_date > now:
                    next_style = tracker_style.get('next-fine', '')
                    last_style = tracker_style.get('next-fine', '')
                    spread_style = tracker_style.get('next-fine', '')
                    name_style = tracker_style.get('next-fine', '')
                else:
                    next_style = tracker_style.get('default', '')
                    last_style = tracker_style.get('default', '')
                    spread_style = tracker_style.get('default', '')
                    name_style = tracker_style.get('default', '')

                # Format each part with fixed width
                tag_formatted = f"  {tag:<5}"          # 7 spaces for tag
                next_formatted = f"{next_date:^8}  "  # 10 spaces for next date
                last_formatted = f"{last_date:^8}  "  # 10 spaces for last date
                if spread == "~":
                    spread_formatted = f"{spread:^8}  "  # 10 spaces for freq
                else:
                    spread_formatted = f"{spread:^8}  "  # 10 spaces for freq
                # Add the styled parts to the tokens list
                tokens.append((tracker_style.get('tag', ''), tag_formatted))
                tokens.append((next_style, next_formatted))
                tokens.append((spread_style, spread_formatted))
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
    today = (datetime.now()-timedelta(days=1)).strftime("%y-%m-%d")
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
            logger.debug(f"new day: {newday}")
            today = newday
            rotate_backups(backup_dir)

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
character_mode = [False]
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
# label = " ▶️"
# tag = "  🏷"
# box = "■" # 0x2588
# line_char = "━"
indent = "   "

# NOTE: zero-width space - to mark trackers with next <= today+oneday
BEF = '\u200B'

tracker_lexer = TrackerLexer()
info_lexer = InfoLexer()
help_lexer = HelpLexer()
default_lexer = DefaultLexer()

display_area = TextArea(text="", read_only=True, search_field=search_field, lexer=tracker_lexer)

def set_lexer(document_type: str):
    if document_type == 'list':
        display_area.lexer = tracker_lexer
    elif document_type == 'info':
        display_area.lexer = info_lexer
    elif document_type == 'help':
        display_area.lexer = help_lexer
    else:
        display_area.lexer = default_lexer


input_area = TextArea(
    focusable=True,
    multiline=True,
    prompt='> ',
    height=D(preferred=1, max=10),  # Set preferred and max height
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
        height=D(preferred=1, max=4),  # Adjust max height as needed
        style="class:message-window"
    )
)

dialog_area = HSplit(
        [
            message_window,
            HorizontalLine(),
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
right_control.text = f"{tracker_manager.sort_by} "


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

def set_mode(mode: str):
    if mode == 'menu':
        # for selecting menu items with a key press
        menu_mode[0] = True
        select_mode[0] = False
        bool_mode[0] = False
        integer_mode[0] = False
        character_mode[0] = False
        dialog_visible[0] = False
        input_visible[0] = False
    elif mode == 'select':
        # for selecting rows by a lower case letter key press
        menu_mode[0] = False
        select_mode[0] = True
        bool_mode[0] = False
        integer_mode[0] = False
        character_mode[0] = False
        dialog_visible[0] = True
        input_visible[0] = False
    elif mode == 'bool':
        # for selecting y/n with a key press
        menu_mode[0] = False
        select_mode[0] = False
        bool_mode[0] = True
        integer_mode[0] = False
        character_mode[0] = False
        dialog_visible[0] = True
        input_visible[0] = False
    elif mode == 'integer':
        # for selecting an single digit integer with a key press
        menu_mode[0] = False
        select_mode[0] = False
        bool_mode[0] = False
        integer_mode[0] = True
        character_mode[0] = False
        dialog_visible[0] = True
        input_visible[0] = False
    elif mode == 'character':
        # for selecting an single digit integer with a key press
        menu_mode[0] = False
        select_mode[0] = False
        bool_mode[0] = False
        integer_mode[0] = False
        character_mode[0] = True
        dialog_visible[0] = True
        input_visible[0] = False
    elif mode == 'input':
        # for entering text in the input area
        menu_mode[0] = False
        select_mode[0] = False
        bool_mode[0] = False
        integer_mode[0] = False
        character_mode[0] = False
        dialog_visible[0] = True
        input_visible[0] = True


tag_msg = "Press the key corresponding to the tag of the tracker"
labels = "abcdefghijklmnopqrstuvwxyz"

tag_keys = list(string.ascii_lowercase)
tag_keys.append('escape')
bool_keys = ['y', 'n', 'escape', 'enter']

# from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application.current import get_app

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application.current import get_app

# @kb.add(*list(labels), filter=Condition(lambda: select_mode[0]))
def get_selection(event):
    global selected_id
    key_pressed = event.key_sequence[0].key
    logger.debug(f"got key: {key_pressed}; action: '{action[0]}'")
    if key_pressed in labels:
        selected_id = tracker_manager.get_id_from_label(key_pressed)
        set_mode('menu')
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

@kb.add('f6')
def do_restore_defaults(*event):
    tracker_manager.restore_defaults()
    display_message("Defaults restored.", 'info')

@kb.add('f7')
def do_help(*event):
    help_text = read_readme()
    display_message(wrap(help_text, 0), 'help')

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
    set_mode('menu')
    display_message(tracker_manager.list_trackers(), 'list')
    app.layout.focus(display_area)
    app.invalidate()

# # @kb.add('S', filter=Condition(lambda: menu_mode[0]))
# def list_settings(*event):
#     """List settings."""
#     action[0] = "list"
#     set_mode('menu')

#     yaml_string = StringIO()

#     # Step 2: Dump the CommentedMap into the StringIO object
#     yaml.dump(settings_map, yaml_string)

#     # Step 3: Get the string from the StringIO object
#     yaml_output = yaml_string.getvalue()


#     # display_message(tracker_manager.list_settings(), 'info')
#     display_message(yaml_output, 'info')
#     app.layout.focus(display_area)
#     app.invalidate()

@kb.add('f5', filter=Condition(lambda: menu_mode[0]))
def refresh_info(*event):
    tracker_manager.refresh_info()
    list_trackers()

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

# @kb.add('r', filter=Condition(lambda: menu_mode[0]))
# def reverse_sort(*event):
#     tracker_manager.next_first = not tracker_manager.next_first
#     right_control.text = "next/last/neither " if tracker_manager.next_first else "neither/last/next "
#     # right_control.text = "next first " if tracker_manager.next_first else "next last "
#     list_trackers()

@kb.add('t', filter=Condition(lambda: menu_mode[0]))
def select_tag(*event):
    """
    From a keypress corresponding to a tag, move the cursor to the row corresponding to the tag and set the selected_id to the id of the corresponding tracker.
    """
    global done_keys, selected_id
    done_keys = [x[1] for x in tracker_manager.tag_to_row.keys() if x[0] == tracker_manager.active_page]
    message_control.text = wrap(f" {tag_msg} you would like to select", 0)
    set_mode('select')

    for key in tag_keys:
        kb.add(key, filter=Condition(lambda: select_mode[0]), eager=True)(lambda event, key=key: handle_key_press(event, key))

    def handle_key_press(event, key):
        key_pressed = event.key_sequence[0].key
        logger.debug(f"{tracker_manager.tag_to_row = }")
        if key_pressed in done_keys:
            set_mode('menu')
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
def inspect_tracker(*event):
    """Show tracker information"""
    global done_keys, selected_id
    tracker = get_tracker_from_row()
    logger.debug(f"in tracker_info: {tracker = }")
    action[0] = "info"
    if tracker:
        logger.debug("got tracker from row, calling process_tracker")
        set_mode('menu')
        display_message(tracker.get_tracker_info(), 'info')
        app.layout.focus(display_area)
        return
        # message_control.text = key_msg
    done_keys = tag_keys
    message_control.text = wrap(f" {tag_msg} you would like to inspect", 0)
    set_mode('select')

    for key in tag_keys:
        kb.add(key, filter=Condition(lambda: select_mode[0]), eager=True)(lambda event, key=key: handle_key_press(event, key))

    def handle_key_press(event, key):
        key_pressed = event.key_sequence[0].key
        logger.debug(f"{tracker_manager.tag_to_row = }")
        if key_pressed in done_keys:
            set_mode('menu')
            message_control.text = ""
            if key_pressed == 'escape':
                return

            tag = (tracker_manager.active_page, key_pressed)
            selected_id = tracker_manager.tag_to_id.get(tag)
            tracker = tracker_manager.get_tracker_from_id(selected_id)
            logger.debug(f"got id {selected_id} and tracker {tracker} from tag {tag}")
            display_message(tracker.get_tracker_info(), 'info')
            app.layout.focus(display_area)


# @kb.add('n', filter=Condition(lambda: menu_mode[0]))
# def new_tracker(*event):
#     """Add a new tracker."""
#     action[0] = "new"
#     menu_mode[0] = False
#     select_mode[0] = False
#     dialog_visible[0] = True
#     input_visible[0] = True
#     message_control.text = wrap(" Enter the name for the new tracker. Append @ followed by an integer number of days to flag this tracker when this number of days has passed since the last completion.", 0)
#     logger.debug(f"action: {action[0]} getting tracker name ...")
#     app.layout.focus(input_area)

#     input_area.accept_handler = lambda buffer: handle_input()

#     @kb.add('c-s', filter=Condition(lambda: action[0]=="new"))
#     def handle_input(event):
#         """Handle input when Enter is pressed."""
#         parts = [x.strip() for x in input_area.text.split()]
#         tracker_name = parts[0]
#         if tracker_name:
#             logger.debug(f"got tracker name: {tracker_name}")
#             tracker_manager.add_tracker(
#                 name=tracker_name,
#                 )
#             input_area.text = ""
#             list_trackers()
#         else:
#             message_control.text = "No tracker name provided."
#             list_trackers()

@kb.add('c-e')
def add_example_trackers(*event):
    import lorem
    from lorem.text import TextLorem
    lm = TextLorem(srange=(2,3))
    import random
    today = datetime.now().replace(microsecond=0,second=0,minute=0,hour=0)
    for i in range(1,49):
        doc_id =tracker_manager.add_tracker(f"# {lm.sentence()[:-1]}") # remove period at end and record for doc_id i+1
        num_completions = random.choice(range(0,9,2))
        days = random.choice(range(1,12))
        offset = timedelta(minutes=-720*days)
        for j in range(num_completions):
            minutes = random.choice(range(-144,144, 12))*days
            offset += timedelta(minutes=days*1440+minutes)
            comp = today - offset
            tracker_manager.trackers[doc_id].record_completion(comp)
        tracker_manager.trackers[doc_id].compute_info()
    list_trackers()

@kb.add('c-r')
def del_example_trackers(*event):
    remove = []
    for id, tracker in tracker_manager.trackers.items():
        if tracker.name.startswith('#'):
            remove.append(id)
    for id in remove:
        tracker_manager.delete_tracker(id)
    list_trackers()


# @kb.add('e', filter=Condition(lambda: menu_mode[0]))
# def edit_history(*event):
#     """Edit a tracker history."""
#     action[0] = "edit"
#     menu_mode[0] = False
#     select_mode[0] = True
#     dialog_visible[0] = True
#     input_visible[0] = False
#     message_control.text = wrap(f" {tag_msg} you would like to edit", 0)

def rename_tracker(*event):
    action[0] = "rename"
    menu_mode[0] = False
    select_mode[0] = True
    dialog_visible[0] = True
    input_visible[0] = False
    message_control.text = wrap(f" {tag_msg} you would like to rename", 0)

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

class Dialog:
    def __init__(self, action_type, kb, tag_keys, bool_keys, tracker_manager, message_control, display_area, wrap):
        self.action_type = action_type
        self.kb = kb
        self.menu_mode = menu_mode
        self.select_mode = select_mode
        self.tag_keys = tag_keys
        self.bool_keys = bool_keys
        self.tracker_manager = tracker_manager
        self.message_control = message_control
        self.display_area = display_area
        self.wrap = wrap
        self.app = None  # Initialize without app

    def set_app(self, app):
        self.app = app

    def set_done_keys(self, done_keys: list[str]):
        self.done_keys = done_keys

    def start_dialog(self, event):
        logger.debug(f"starting dialog for action {self.action_type}")
        if self.action_type in [
            "complete", "delete", "edit", "rename"
            ]:
            tracker = get_tracker_from_row()
            action[0] = self.action_type
            if tracker:
                self.selected_id = tracker.doc_id
                logger.debug(f"got tracker from row")
                self.set_input_mode(tracker)
            else:
                self.done_keys = self.tag_keys
                self.message_control.text = self.wrap(f" {tag_msg} you would like to {self.action_type}", 0)
                self.set_select_mode()

        elif self.action_type == "new":  # new tracker
            self.set_input_mode(None)

        elif self.action_type == "settings":
            self.set_input_mode(None)

        elif self.action_type == "sort":
            self.set_sort_mode(None)


    def set_input_mode(self, tracker):
        set_mode('input')
        if self.action_type == "complete":
            self.message_control.text = wrap(f' Enter the new completion datetime for "{tracker.name}" (doc_id {self.selected_id})', 0)
            self.app.layout.focus(input_area)
            input_area.accept_handler = lambda buffer: self.handle_completion()
            self.kb.add('enter')(self.handle_completion)
            # self.kb.add('c-s')(self.handle_completion)
            self.kb.add('c-c', eager=True)(self.handle_cancel)

        elif self.action_type == "edit":
            self.message_control.text = wrap(f' Edit the completion datetimes for "{tracker.name}" (doc_id {self.selected_id})\n Press "enter" to save changes or "^c" to cancel', 0)
            # put the formatted completions in the input area
            input_area.text = wrap(tracker.format_history(), 0)
            self.app.layout.focus(input_area)
            input_area.accept_handler = lambda buffer: self.handle_history()
            self.kb.add('enter')(self.handle_history)
            # self.kb.add('c-s')(self.handle_history)
            self.kb.add('c-c', eager=True)(self.handle_cancel)

        elif self.action_type == "rename":
            self.message_control.text = wrap(f' Edit the name of "{tracker.name}" (doc_id {self.selected_id})\n Press "enter" to save changes or "^c" to cancel', 0)
            # put the formatted completions in the input area
            input_area.text = wrap(tracker.name, 0)
            self.app.layout.focus(input_area)
            input_area.accept_handler = lambda buffer: self.handle_rename()
            self.kb.add('enter')(self.handle_rename)
            # self.kb.add('c-s')(self.handle_rename)
            self.kb.add('c-c', eager=True)(self.handle_cancel)

        elif self.action_type == "settings":
            self.message_control.text = " Edit settings. \nPress 'enter' to save changes or '^c' to cancel"
            settings_map = self.tracker_manager.settings
            yaml_string = StringIO()
            # Step 2: Dump the CommentedMap into the StringIO object
            yaml.dump(settings_map, yaml_string)
            # Step 3: Get the string from the StringIO object
            yaml_output = yaml_string.getvalue()
            input_area.text = yaml_output
            self.app.layout.focus(input_area)
            input_area.accept_handler = lambda buffer: self.handle_settings()
            self.kb.add('enter')(self.handle_settings)
            # self.kb.add('c-s')(self.handle_settings)
            self.kb.add('escape', eager=True)(self.handle_cancel)

        elif self.action_type == "new":
            self.message_control.text = """\
 Enter the name of the new tracker. Optionally append a comma and the datetime
 of the first completion, and again, optionally, another comma and the timedelta
 of the expected interval until the next completion, e.g. 'name, 3p wed, +7d'.
 Press 'enter' to save changes or '^c' to cancel.
"""
            self.app.layout.focus(input_area)
            input_area.accept_handler = lambda buffer: self.handle_new()
            self.kb.add('enter')(self.handle_new)
            self.kb.add('escape', eager=True)(self.handle_cancel)

        elif self.action_type == "delete":
            self.message_control.text = f'Are you sure you want to delete "{tracker.name}" (doc_id {self.selected_id}) (Y/n)?'
            self.set_bool_mode()

    def set_select_mode(self):
        set_mode('select')
        for key in self.tag_keys:
            self.kb.add(key, filter=Condition(lambda: self.select_mode[0]), eager=True)(lambda event, key=key: self.handle_key_press(event, key))

    def set_sort_mode(self, event=None):
        set_mode('character')
        self.message_control.text = wrap(f" Sort by f)orecast, l)atest, n)ame or i)d", 0)
        self.set_done_keys(['f', 'l', 'n', 'i', 'escape'])
        for key in self.done_keys:
            self.kb.add(key, filter=Condition(lambda: character_mode[0]), eager=True)(lambda event, key=key: self.handle_sort(event, key))

    def handle_key_press(self, event, key_pressed):
        logger.debug(f"{key_pressed = }")
        if key_pressed in self.done_keys:
            if key_pressed == 'escape':
                set_mode('menu')
                return
            tag = (self.tracker_manager.active_page, key_pressed)
            self.selected_id = self.tracker_manager.tag_to_id.get(tag)
            tracker = self.tracker_manager.get_tracker_from_id(self.selected_id)
            logger.debug(f"got id {self.selected_id} from tag {tag}")
            self.set_input_mode(tracker)

    def set_bool_mode(self):
        set_mode('bool')
        for key in self.bool_keys:
            self.kb.add(key, filter=Condition(lambda: action[0] == self.action_type), eager=True)(lambda event, key=key: self.handle_bool_press(event, key))

    def handle_bool_press(self, event, key):
        logger.debug(f"got key {key} for {self.action_type} {self.selected_id}")
        if key == 'y' or key == 'enter' and self.action_type == "delete":
            self.tracker_manager.delete_tracker(self.selected_id)
            logger.debug(f"deleted tracker: {self.selected_id}")
        set_mode('menu')
        list_trackers()
        self.app.layout.focus(self.display_area)

    def handle_completion(self, event=None):
        completion_str = input_area.text.strip()
        logger.debug(f"got completion_str: '{completion_str}' for {self.selected_id}")
        if completion_str:
            ok, completion = Tracker.parse_completion(completion_str)
            if ok:
                logger.debug(f"recording completion_dt: '{completion}' for {self.selected_id}")
                self.tracker_manager.record_completion(self.selected_id, completion)
                close_dialog()
        else:
            self.display_area.text = "No completion datetime provided."
        set_mode('menu')
        self.app.layout.focus(self.display_area)

    def handle_history(self, event=None):
        history = input_area.text.strip()
        logger.debug(f"got history: '{history}' for {self.selected_id}")
        if history:
            ok, completions = Tracker.parse_completions(history)
            if ok:
                logger.debug(f"recording '{completions}' for {self.selected_id}")
                self.tracker_manager.record_completions(self.selected_id, completions)
                close_dialog()
            else:
                display_message(f"Invalid history: '{completions}'", 'error')

        else:
            display_message("No completion datetime provided.", 'error')
        set_mode('menu')
        self.app.layout.focus(self.display_area)

    def handle_edit(self, event=None):
        completion_str = input_area.text.strip()
        logger.debug(f"got completion_str: '{completion_str}' for {self.selected_id}")
        if completion_str:
            ok, completions = Tracker.parse_completions(completion_str)
            logger.debug(f"recording completion_dt: '{completion}' for {self.selected_id}")
            self.tracker_manager.record_completions(self.selected_id, completion)
            close_dialog()
        else:
            self.display_area.text = "No completion datetime provided."
        set_mode('menu')
        self.app.layout.focus(self.display_area)


    def handle_rename(self, event=None):
        name_str = input_area.text.strip()
        logger.debug(f"got name_str: '{name_str}' for {self.selected_id}")
        if name_str:
            self.tracker_manager.trackers[self.selected_id].rename(name_str)
            logger.debug(f"recorded new name: '{name_str}' for {self.selected_id}")
            close_dialog()
        else:
            self.display_area.text = "New name not provided."
        set_mode('menu')
        list_trackers()
        self.app.layout.focus(self.display_area)

    def handle_settings(self, event=None):

        yaml_string = input_area.text
        if yaml_string:
            yaml_input = StringIO(yaml_string)
            updated_settings = yaml.load(yaml_input)

            # Step 2: Update the original CommentedMap with the new data
            # This will overwrite only the changed values while keeping the structure.
            self.tracker_manager.settings.update(updated_settings)
            transaction.commit()
            logger.debug(f"updated settings:\n{yaml_string}")
            close_dialog()
        set_mode('menu')
        list_trackers()
        self.app.layout.focus(self.display_area)

    def handle_new(self, event=None):
        name = input_area.text.strip()
        msg = []
        if name:
            parts = [x.strip() for x in name.split(",")]
            name = parts[0] if parts else None
            date = parts[1] if len(parts) > 1 else None
            interval = parts[2] if len(parts) > 2 else None
            if name:
                doc_id = self.tracker_manager.add_tracker(name)
                logger.debug(f"added tracker: {name}")
            else:
                msg.append("No name provided.")
            if date and not msg:
                dtok, dt = Tracker.parse_dt(date)
                if not dtok:
                    msg.append(dt)
                else:
                    # add an initial completion at dt
                    self.tracker_manager.record_completion(doc_id, (dt, timedelta(0)))
            if interval and not msg:
                tdok, td = Tracker.parse_td(interval)
                if not tdok:
                    msg.append(td)
                else:
                    # add a fictitious completion at td before dt
                    self.tracker_manager.record_completion(doc_id, (dt-td, timedelta(0)))
            close_dialog()
        if msg:
            self.display_area.text = "\n".join(msg)
        set_mode('menu')
        list_trackers()
        self.app.layout.focus(self.display_area)

    def handle_sort(self, event=None, key_pressed=None):
        if key_pressed in self.done_keys:
            if key_pressed == 'escape':
                set_mode('menu')
                return
            if key_pressed == 'f':
                self.tracker_manager.sort_by = 'forecast'
            elif key_pressed == 'l':
                self.tracker_manager.sort_by = 'latest'
            elif key_pressed == 'n':
                self.tracker_manager.sort_by = 'name'
            elif key_pressed == 'i':
                self.tracker_manager.sort_by = 'id'
            right_control.text = f"{self.tracker_manager.sort_by} "
            list_trackers()
            self.app.layout.focus(self.display_area)

    def handle_cancel(self, event=None, key_pressed=None):
        if key_pressed == 'escape':
            set_mode('menu')
            return
        close_dialog()


# Dialog usage:
dialog_new = Dialog("new", kb, tag_keys, bool_keys, tracker_manager, message_control, display_area, wrap)
kb.add('n', filter=Condition(lambda: menu_mode[0]))(dialog_new.start_dialog)

dialog_complete = Dialog("complete", kb, tag_keys, bool_keys, tracker_manager, message_control, display_area, wrap)
kb.add('c', filter=Condition(lambda: menu_mode[0]))(dialog_complete.start_dialog)

dialog_edit = Dialog("edit", kb, tag_keys, bool_keys, tracker_manager, message_control, display_area, wrap)
kb.add('e', filter=Condition(lambda: menu_mode[0]))(dialog_edit.start_dialog)

dialog_rename = Dialog("rename", kb, tag_keys, bool_keys, tracker_manager, message_control, display_area, wrap)
kb.add('r', filter=Condition(lambda: menu_mode[0]))(dialog_rename.start_dialog)

dialog_settings = Dialog("settings", kb, tag_keys, bool_keys, tracker_manager, message_control, display_area, wrap)
kb.add('f4', filter=Condition(lambda: menu_mode[0]))(dialog_settings.start_dialog)

dialog_delete = Dialog("delete", kb, tag_keys, bool_keys, tracker_manager, message_control, display_area, wrap)
kb.add('d', filter=Condition(lambda: menu_mode[0]))(dialog_delete.start_dialog)

dialog_sort = Dialog("sort", kb, tag_keys, bool_keys, tracker_manager, message_control, display_area, wrap)
kb.add('s', filter=Condition(lambda: menu_mode[0]))(dialog_sort.start_dialog)


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
                MenuItem('F4) edit settings', handler=lambda: dialog_settings.start_dialog(None)),
                MenuItem('F5) refresh info', handler=refresh_info),
                MenuItem('F6) restore default settings', handler=do_restore_defaults),
                MenuItem('F7) help', handler=do_help),
                MenuItem('^q) quit', handler=exit_app),
            ]
        ),
        MenuItem(
            'edit',
            children=[
                MenuItem('n) add new tracker', handler=lambda: dialog_new.start_dialog(None)),
                MenuItem('c) add completion', handler=lambda: dialog_complete.start_dialog(None)),
                MenuItem('d) delete tracker', handler=lambda: dialog_delete.start_dialog(None)),
                MenuItem('e) edit history', handler=lambda: dialog_edit.start_dialog(None)),
                MenuItem('r) rename tracker', handler=lambda: dialog_rename.start_dialog(None)),
            ]
        ),
        MenuItem(
            'view',
            children=[
                MenuItem('i) tracker info', handler=inspect_tracker),
                MenuItem('l) list trackers', handler=list_trackers),
                MenuItem('s) sort', handler=lambda: dialog_sort.start_dialog(None)),
                MenuItem('t) select tag', handler=select_tag),
            ]
        ),
    ]
)

layout = Layout(root_container)
# app = Application(layout=layout, key_bindings=kb, full_screen=True, style=style)

app = Application(layout=layout, key_bindings=kb, full_screen=True, mouse_support=True, style=style)

app.layout.focus(root_container.body)

for dialog in [dialog_new, dialog_complete, dialog_delete, dialog_edit, dialog_sort, dialog_rename, dialog_settings]:
    dialog.set_app(app)

# dialog_new.set_app(app)
# dialog_complete.set_app(app)
# dialog_delete.set_app(app)

def main():
    # global tracker_manager
    try:
        logger.info(f"Started TrackerManager with database file {db_file}")

        display_text = tracker_manager.list_trackers()
        display_message(display_text)
        start_periodic_checks()  # Start the periodic checks
        app.run()
    except Exception as e:
        logger.error(f"exception raised:\n{e}")
    else:
        logger.error("exited tracker")
    finally:
        if tracker_manager:
            tracker_manager.close()
            logger.info(f"Closed TrackerManager and database file {db_file}")
        else:
            logger.info("TrackerManager was not initialized")
            print("")

if __name__ == '__main__':
    main()