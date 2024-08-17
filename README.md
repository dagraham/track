# track

This is a simple application for tracking occasions in which particular tasks are completed.

As an example, consider the task of "filling the bird feeders". Suppose you want to have an idea when you should next fill them. One approach would be to set a reminder to fill them every 14 days starting from the last time you filled them. When the reminder is triggered, you could check the feeders to see if they are empty. If they are, you could fill them and then perhaps adjust the reminder to repeat every 12 days. On the other hand, if they are not empty, you might adjust the reminder to repeat every 16 days. Repeating this process, you might eventually set a repetition frequency for the reminder that well predicts the next time you should fill them.

The goal of *track* is to save you trouble of going through this iterative process. Here's how it works:

1. In *track*, press "a" to add a new tracker and name it "fill bird feeders"
2. The first time you fill the feeders, press "c" to add a completion, select the "fill bird feeders" tracker and enter the date and time of the completion. This date and time will be added to the history of completions for the "fill bird feeders" tracker.
3. The next time you need to fill the feeders, repeat the process described in step 2. At this point, you will have two datetimes in the history of the tracker and track will calculate the interval between them and set the "expected next completion" by adding the interval to last completion date and time.
4. The process repeats with each completion. There are only two differences when there are more than 2 completions:
   - The "expected next completion" is calculated by adding the *average* of the intervals to the last completion date and time.
   - If there are more than 12 completions, only the last 12 completions are used to calculate the average interval. The estimated next completion date and time is thus based only on the most recent 12 completions.




