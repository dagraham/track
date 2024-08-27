#! /usr/bin/env python3
# NOTE: Tracker and TrackerManager Classes
from prompt_toolkit import prompt
from prompt_toolkit.validation import Validator, ValidationError
import re
from typing import List, Dict, Any, Callable, Mapping
from collections import defaultdict
import json
import os
from datetime import datetime, timedelta
from dateutil.parser import parse, parserinfo
import traceback
import sys

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


class Tracker:
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
        # completion_dt will be a valid datetime
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
    def __init__(self, file_path=None) -> None:
        if file_path is None:
            file_path = os.path.join(os.getcwd(), "tracker.json")
        self.file_path = file_path
        self.trackers = {}
        print(f"loading data from {self.file_path}")
        self.load_data(self.file_path)

    def add_tracker(self, tracker) -> None:
        doc_id = tracker.doc_id
        print(f"adding tracker {doc_id}; {type(doc_id) = }")
        self.trackers[doc_id] = tracker
        self.save_data(self.file_path)

    def record_completion(self, doc_id: int, completion: tuple[datetime, timedelta]):
        ok, msg = self.trackers[doc_id].record_completion(completion)
        if not ok:
            print(msg)
            return

        self.save_data(self.file_path)
        dt, td = completion
        print(f"""\
    {doc_id}: Recorded ({dt.strftime('%Y-%m-%d %H:%M')}, {Tracker.format_td(td)}) as a completion:\n    {self.trackers[doc_id].get_tracker_data()}""")

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
            # print(f"{k}. {v}")
            print(f"   {int(k):2> }. {v.name}")

    def save_data(self, file_path):
        data = {int(doc_id): {
                    'name': tracker.name,
                    'history': [Tracker.format_dt(dt) for dt in tracker.history],
                } for doc_id, tracker in self.trackers.items()}
        with open(file_path, 'w') as file:
            json.dump(data, file, indent=2)

    def load_data(self, file_path):
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)
                _max_id = 0
                for doc_id, tracker_data in data.items():
                    doc_id = int(doc_id)
                    _max_id = max(doc_id, _max_id)
                    tracker = Tracker(tracker_data['name'], doc_id)
                    tracker.history = [Tracker.parse_dt(dt) for dt in tracker_data['history']]
                    self.trackers[doc_id] = tracker
                Tracker._next_id = _max_id + 1
        except FileNotFoundError:
            print(f"Warning: could not load data from '{file_path}'")
            self.trackers = {}

    @staticmethod
    def parse_timedelta(td_str):
        if not td_str:
            return None
        else:
            total_seconds = int(td_str)
            return timedelta(seconds=total_seconds)

    def update_tracker(self, doc_id, tracker):
        self.trackers[doc_id] = tracker
        self.save_data(self.file_path)

    def delete_tracker(self, doc_id):
        if doc_id in self.trackers:
            del self.trackers[doc_id]
            self.save_data(self.file_path)

    def get_tracker(self, doc_id):
        return self.trackers.get(doc_id, None)

def main():
    file_path = os.path.join(os.getcwd(), "tracker.json")
    if not os.path.exists(file_path):
        print(f"Warning: '{file_path}' does not exist and will be created.")
        ok = input("Continue? (y/n) ").strip().lower() == 'y'
        if not ok:
            sys.exit("Aborted.")
    tracker_manager = TrackerManager(file_path)
    tracker_manager.list_trackers()
    last_id = None
    clear_screen()

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
            sys.exit()

        else:
            print("Invalid option. Please choose again.")

if __name__ == "__main__":
    main()

