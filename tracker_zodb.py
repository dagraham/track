#! /usr/bin/env python3
from prompt_toolkit import prompt
from prompt_toolkit.validation import Validator, ValidationError
import re
from typing import List, Dict, Any, Callable, Mapping
from collections import defaultdict
from datetime import datetime, timedelta
from dateutil.parser import parse, parserinfo
import traceback
import sys
from ZODB import DB, FileStorage
from persistent import Persistent
import transaction
import os

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


class Tracker(Persistent):
    _next_id = 1
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

    def __init__(self, name: str, doc_id: int = None) -> None:
        if doc_id is None:
            self.doc_id = Tracker._next_id
            Tracker._next_id += 1
        else:
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
        invervals ({len(intervals)}):
            average: {Tracker.format_td(average_interval)}
            last: {Tracker.format_td(last_interval)}
            change: {Tracker.format_td(change)}
        completions ({len(self.history)}):
            last: {Tracker.format_dt(last_completion)}
            next: {Tracker.format_dt(next_expected_completion)}
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
        print(f"loading data from {self.db_path}")
        self.load_data()

    def add_tracker(self, tracker) -> None:
        doc_id = tracker.doc_id
        self.trackers[doc_id] = tracker
        self.save_data()

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
            self.trackers = self.root.get('trackers', {})
            if self.trackers:
                _max_id = max(self.trackers.keys())
                Tracker._next_id = _max_id + 1
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

    def get_tracker(self, doc_id):
        return self.trackers.get(doc_id, None)

    def close(self):
        self.connection.close()
        self.db.close()
        self.storage.close()

def main():
    db_path = os.path.join(os.getcwd(), "tracker.fs")
    tracker_manager = TrackerManager(db_path)
    tracker_manager.list_trackers()
    last_id = None
    clear_screen()

    try:
        while True:
            print("Menu:")
            print("    a) add tracker")
            print("    d) delete tracker")
            print("    l) list trackers")
            print("    r) record completion")
            print("    s) show tracker info")
            print("    c) clear screen")
            print("    q) quit")

            choice = input("Choose an option: ").strip().lower()

            if choice == 'a':
                name = input("Enter tracker name: ").strip()
                new_tracker = Tracker(name)
                tracker_manager.add_tracker(new_tracker)
                print(f"{type(new_tracker.doc_id) = }")
                last_id = new_tracker.doc_id
                print(f"Tracker '{name}' added with ID {new_tracker.doc_id}")

            elif choice == 'd':
                try:
                    doc_id_input = input(f"Enter tracker ID to delete [{last_id}]: ").strip()
                    doc_id = int(doc_id_input) if doc_id_input else last_id
                    if doc_id is not None:
                        tracker_manager.delete_tracker(doc_id)
                        print(f"Tracker with ID {doc_id} deleted")
                    else:
                        print("No ID provided.")
                except ValueError:
                    print("Invalid ID. Please enter a numeric value.")

            elif choice == 'l':
                tracker_manager.list_trackers()

            elif choice == 'r':
                tracker_manager.list_trackers()
                try:
                    doc_id_input = input(f"Enter tracker ID [{last_id}]: ").strip()
                    doc_id = int(doc_id_input) if doc_id_input else last_id
                    if doc_id is not None:
                        last_id = doc_id
                        dt_str = input(f"Enter completion datetime for {doc_id}: ").strip()
                        dt = Tracker.parse_dt(dt_str)
                        if dt:
                            tracker_manager.record_completion(doc_id, dt)
                        else:
                            print("Invalid datetime format. Please try again.")
                    else:
                        print("No ID provided.")
                except ValueError:
                    print("Invalid ID. Please enter a numeric value.")

            elif choice == 's':
                try:
                    doc_id_input = input(f"Enter tracker ID (or 0 for all) [{last_id}]: ").strip()
                    doc_id = int(doc_id_input) if doc_id_input else last_id
                    if doc_id is not None:
                        if doc_id == 0:
                            tracker_manager.get_tracker_data()
                        else:
                            last_id = doc_id
                            tracker_manager.get_tracker_data(doc_id)
                    else:
                        print("No ID provided.")
                except ValueError:
                    print("Invalid ID. Please enter a numeric value.")

            elif choice == 'c':
                clear_screen()

            elif choice == 'q':
                print("Quitting...")
                break

            else:
                print("Invalid option. Please choose again.")
    finally:
        tracker_manager.close()

if __name__ == "__main__":
    main()
