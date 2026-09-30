---
name: bounding-heavy-commands
description: Use when about to run a project's test suite, linter, build, type check, or another command of that weight, when about to dispatch subagents that will run one, or when a command fails on a port already in use, a tool's own lock, or a machine that slows down or swaps while agents verify their work.
---

# bounding-heavy-commands

## Overview

Every heavy command an agent starts goes through the wrapper. There is no exception for a session that looks alone, for a command that looks small, or for a user who is in a hurry. Two sections say when a command runs without the wrapper: §When an instruction sends a command around the wrapper, and §When the wrapper cannot run. No other case exists.

A machine freezes because of the heavy commands that run on it, not because of the number of agents. Sessions in other terminals and other projects run their own test suites and builds at the same moment, and no session can see the others. When the commands together need more memory than the machine has, it swaps until it stops responding, and that costs every session, not only the one that started the last command. The wrapper makes the commands of every session and every project on the machine take turns on its memory, so too much work shows up as a queue instead of a freeze.

**Looking first does not protect the machine.** Two sessions that look at the load at the same moment both see a quiet machine, and both start. A sum of budgets against the machine's total memory does not protect it either: the sum counts your commands and no one else's. Only a reservation that every session takes before it starts can count the commands, and the wrapper is that reservation. The check of the wrapper looks too, but it decides which measured row to queue, never whether to queue (§The record).

**Violating the letter of these rules is violating their spirit.**

## When to invoke

- Before you run the project's test suite, linter, build, or type check, or anything that compiles, starts containers, or starts a local cluster.
- Before you dispatch subagents that will run any of those.
- When a command failed on a port that is already in use, or on a tool's own lock.
- When the machine is slow or swaps and someone asks what to change.

A command is heavy when the project's record says so, or when it compiles, tests, checks, generates, or installs over more than a handful of files. An install of the dependencies, a code generator, and a formatter over the whole tree are heavy. So is a commit or a push in a project whose hooks run the tests or the linter. A part of a heavy command is heavy too: one test file, one package, one target. When in doubt, it is heavy: the wrapper costs a second, a frozen machine costs every session.

Skip for commands that only read (listing files, searching, version-control queries). Do not add the wrapper to the project's scripts, to its CI configuration, or to the commands that a person types: this skill is for the commands that an agent starts on a machine that it shares.

A command that does not end, such as a server or a watch mode, holds its memory in the queue until it stops. Start it through the wrapper, and stop it when your work with it is done.

A server that a heavy command talks to is a part of that command: a development server, a database, or a container that a test suite sends its requests to. The work of the suite grows the server, and the budget of the suite does not count a server outside it. When the test runner can start the server itself, let it: give the run a port that no running server uses, so that the server starts inside the bounded command and its budget covers it. When the server must run on its own, start it through the wrapper. Do not run a heavy command against a server that runs outside the queue, also when it already listens on the port: an agent or a person started it without the wrapper, and the queue cannot count it. Do not stop that server either, because it belongs to someone else. Use a port of your own.

## The wrapper

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --memory <budget> [--cpus <n>] [--exclusive <name>]... [--measure] [--label <name>] -- <command>
python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --measure-rows <n>,<n>,... [--memory <budget>] [--exclusive <name>]... [--label <name>] -- <command>
python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --check [--memory <budget>]...
```

| Option | Meaning |
| --- | --- |
| `--memory <budget>` | Memory the command may use, such as `6G` or `4096M`. Taken from the record. Without it the wrapper uses its default budget, a quarter of the machine's memory. A measurement without it takes the whole queue where there is no hard cap. |
| `--cpus <n>` | Processor limit, as a whole number. Taken from the record. |
| `--exclusive <name>` | A resource that only one command may hold at a time, such as a fixed port. You choose the name. The wrapper keeps the names of each repository apart, and all worktrees of one repository share them. Repeat the option for each resource. |
| `--measure` | Also print a suggested budget. Discovery uses it. With no `--memory`, the command runs with the default budget where the hard cap is available, and alone in the queue where it is not. |
| `--measure-rows <n>,<n>,...` | Measure the command one time at each `--cpus` of the list, one after the other, the largest first. The largest runs with the `--memory` of the call. With no `--memory`, it runs with the default budget where the hard cap is available, and alone in the queue where it is not. Each smaller one runs with `--memory` at the suggested budget of the one before it. When the one before it did not exit 0, the smaller one runs with the same `--memory` as that one. Use it in place of `--cpus` and `--measure`. A stop signal ends the list. A stop signal to the wrapper then ends the wrapper by that signal. So a Ctrl-C, which reaches the shell too, stops a line of joined calls; a signal sent to the wrapper alone does not stop the shell's line. Otherwise the exit code is the first exit code of a row that is not 0. |
| `--label <name>` | A name for the row lines of a measurement, such as `unit-tests`. Use letters, digits, `.`, `_`, and `-`, and start with a letter or a digit. It changes nothing else. |
| `--check` | Run no command. Print the state of the queue now, and for each `--memory`, whether a command of that budget would start now. It takes only `--memory`, which you can repeat. It holds no slot, and its exit code is 0. §The record says how to choose a row with it. |

The wrapper does four things in sequence. It waits for its turn in the queue. It waits until the memory of its budget is free. It runs the command. It prints the budget and the measured peak on the error stream. For the wait, the free memory is the memory that the machine has free now, less the part of their budgets that the running bounded commands do not use yet, less a headroom for the programs outside the queue. The headroom is a tenth of the memory of the machine, and at least 1 GiB. The budget and the headroom together never need more than the memory of the queue, so a budget of the whole queue does not wait for a headroom. The wait has no time limit: the command does not start before its memory is free, and the wrapper prints a line at intervals while it waits. Each line that the wrapper prints starts with `bounded-run:`. A measurement also prints one row line, in a fixed form:

```
bounded-run: row label=<name> cpus=<n> budget=<n>M peak=<n>M held=<n>M|- exact=<yes|no> exit=<code>
```

`budget` is the suggested budget. `peak` is the peak of all memory of the command, with the file cache that the kernel can take back from it. `held` is the peak of the memory that the kernel cannot take back at once. It needs the hard cap: without it, the row line shows `held=-`. With `held`, the suggested budget is `held` plus a margin, but at least a quarter of `peak` plus a margin, so that the files the command reads stay in the cache. It is never more than `peak` plus a margin. Without `held`, it is `peak` plus a margin. `exact=no` means that the peak was sampled, so the margin is larger. `held` is always sampled. A `-` in place of the label or the `--cpus` means that the call did not give the option. The wrapper cannot know if the command did its full work: the exit code and the output of the command tell you (§Discovery, step 5).

A check prints its lines in a fixed form too:

```
bounded-run: check slots=<n> slot=<n>M free-slots=<n> free=<n>M unused=<n>M line=<free|busy>
bounded-run: check held unit=<name> budget=<n>M used=<n>M age=<n>s dir=<directory> command=<command>
bounded-run: check budget=<n>M slots=<n> headroom=<n>M starts=<yes|no>
```

The first line gives the slots of the queue and their size, the slots that are free now, the free memory, and the unused budgets of the running commands. `line=busy` means that a command waits in the line. Each `held` line is one bounded command that runs now: its budget, the memory it uses, how long it has run, its working directory, and its command. The held lines need the hard cap, so without it there are none. Each `budget` line is one `--memory`, in the order given: the slots that it needs, the headroom that the wait keeps free beside that budget, and `starts=yes` when a command of that budget would start now. A `-` means that the check cannot read or count the value at that moment.

The exit code of the wrapper is the command's exit code. Exit code 125, with a `bounded-run:` line that names a fault and with no line for the budget and the peak, means that the wrapper itself failed (see §When the wrapper cannot run).

The wrapper sets `BOUNDED_RUN_CPUS` and `BOUNDED_RUN_MEMORY_MIB` in the environment of the command, from `--cpus` and `--memory`. A recorded command line can read them and hand them to the toolchain's own parallelism and memory settings. You do not set them: you change them with the two options.

On Linux the wrapper also puts a hard cap on the command where the system allows it: a command that passes its budget is stopped with exit code 137, and the machine does not swap. Elsewhere there is no hard cap, the wrapper says so in its output, and the queue and the wait are the whole protection. Without the cap, and on a system with cgroup version 1, the wait does not count the unused budgets of the running commands. When a recorded command ends with exit code 137 and the wrapper reports a peak near the budget, the cap stopped it: the command grew. Measure it again with `--measure` and `--memory` at two times the budget, and correct the record.

## The record

Budgets and command lines are facts about one machine and one user, so they live in your project memory (the notes that your harness keeps for this project between sessions), not in the repository. The record is one memory named `bounded-heavy-commands`. Your harness decides the file format. This skill decides the content.

Each heavy command has one entry, in this shape:

```
- <what it is for: "unit tests", "lint", "build">
  plain: <the plain command>
  self-bound: <the setting in the command line that reads BOUNDED_RUN_CPUS or BOUNDED_RUN_MEMORY_MIB, or "none: <why the tool has no such setting>">
  command: python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --memory <budget of the default row> --cpus <--cpus of the default row> [--exclusive <name>]... -- <the command with its self-bound>
  exclusive: <each exclusive resource, or "none">
  rows:
    | --cpus | budget | peak | date | default |
    | <n> | <budget> | <peak> | <date> | yes |
```

A budget is valid only at the `--cpus` of its row. The same command at more processors runs more things at once and needs more memory. So each row is a different measured command, and a run takes its `--cpus` and its `--memory` from one row. The command line of the entry carries the values of the default row. To use a different row, replace both values with the values of that row.

The table has one row for each `--cpus`. A measurement at a `--cpus` that has no row adds a row. A measurement at a `--cpus` that has a row replaces that row. Never delete a row because a different `--cpus` was measured. Two entries whose command lines differ only in the values of the wrapper's `--memory` and `--cpus`, before the `--`, are one entry: keep one, with the rows of both, and where both have a row at the same `--cpus`, keep the newer one. The row at the `--cpus` of the default row of the entry that you keep stays the default row, and no other row is marked as the default. Then write the `--cpus` and the budget of the default row into the command line. One row is the default row. A run uses it when nothing asks for a different one.

Before a run of a command whose entry has more than one row, choose the row with the check. Run the wrapper with `--check` and one `--memory` for the budget of each row. Choose the largest row that would start now (`starts=yes`). When no row would start now, choose the default row and let it wait in the queue: the smallest row runs slowest, and the line keeps the wait fair. Then run the chosen row through the wrapper, with the `--cpus` and the `--memory` of that row. An entry with one row needs no check.

The check is a snapshot, not a reservation. Two sessions can see the same free slots at the same moment, so the chosen row still goes through the queue. A check never replaces the wrapper.

An entry is complete when it has a `self-bound` field, at least one row, and one default row whose `--cpus` and budget are the values in its command line. An entry without the `self-bound` field is incomplete, also when it has a budget: its budget can be the peak of a command that nothing limits. An entry from an older shape of this record, with one budget and no table, is complete in one case only: its command line passes `--cpus` to the wrapper, before the `--`, and reads `BOUNDED_RUN_CPUS`. Then rewrite it into this shape. The setting that reads the variable is its `self-bound`, and its budget, peak, and date become the default row at that `--cpus`.

Then, before each heavy command, use the first case that applies:

1. **Your prompt carries bounded command lines.** You are a subagent. Use them under the rule that your prompt gives with them, and run no discovery. For a heavy command that your prompt does not carry, use the wrapper with no `--memory` option.
2. **The record exists and has a complete entry for the command.** Check that the plain command still exists in the project, and that the file of the wrapper in the command line still exists. When the file of the wrapper is not there, an update of the plugin moved it. The command line in §The wrapper shows the correct path: put it into each command line of the record. Then use the bounded command line with the row that you chose.
3. **The record exists, and the command is not in it, its entry is incomplete, or its entry is no longer correct.** Run the discovery for that command and correct the entry. When the command line changes in more than the values of the wrapper's `--memory` and `--cpus`, its rows measured a different command: delete them, and measure the new command line. Remove an entry whose command the project no longer has.
4. **Your harness has no project memory, or it is off.** You cannot save a record, so do not try. Run the discovery in this session, keep the result in your context, and use the wrapper's default budget for anything you could not measure.
5. **Project memory is on, and the record does not exist.** Run the discovery for every heavy command of the project, not only for the command that you are about to run, and measure them all with one command line that the user runs (§Measure the whole project). While you wait for the answer of the user and for the line, run a heavy command that you need through the wrapper, as its bounded command line at `--cpus` of half the machine's processors, with no `--memory` option.

A budget is a measurement, not a preference. Change a row only when the wrapper's output at the `--cpus` of that row shows that the suggested budget moved, and write the new budget, peak, and date in it. Under the hard cap the budget follows `held`, so it can move while `peak` stays the same.

To make a run start sooner, use a row at a smaller `--cpus`. That command runs fewer things at once, so its peak and its budget are smaller. It gets a slot sooner only when its budget needs fewer slots of the queue than the budget of the default row. It is a different measured command, not a lower budget for the same command. This works only for a command whose `self-bound` reads `BOUNDED_RUN_CPUS`. For any other command, a smaller `--cpus` does not make the command run fewer things at once: keep the run in the queue, and measure no smaller row. When the entry has no row at a smaller `--cpus`, the current run cannot start sooner: keep it in the queue. Then measure the command with `--measure`, with `--cpus` at half the smallest `--cpus` of the table, rounded down, and with `--memory` at the budget of the smallest row, in place of the two values of the command line, and add the row, so that the next run can use it. A command that runs fewer things at once seldom needs more than that budget, and with `--memory` the measurement does not take the whole queue. When the hard cap stops it, measure it again with two times that budget, as step 5 of §Discovery says. At `--cpus 1` no smaller command exists. Keep the default row as it is, unless the user wants the smaller `--cpus` for each run.

A part of a recorded command (one test file, one target) uses the bounded command line of the full command, with a row of its entry and its exclusive resources, and the narrower arguments at the end of the line. It needs no entry of its own and no measurement, because the budget of the full command is sufficient for each part of it.

## Discovery

1. Find how the project runs its tests, its linter, its build, and its type check, and each other heavy command (§When to invoke): code generators, installs, formatters over the whole tree. Read the project's instruction files, its build configuration, and its CI configuration.
2. Bound the command before you measure it. Do not measure a command until this step is done. Find what makes the toolchain run fewer things at once: a flag or a variable for the number of jobs, workers, processes, or threads. Find a memory setting too, but only one that covers the whole command. A memory setting for one process does not cover the processes that it starts. Most tools that start many processes have no memory setting for the whole command, so the number of things that run at once is the main way to lower the peak. Write the command line so that it takes the setting from `BOUNDED_RUN_CPUS` or `BOUNDED_RUN_MEMORY_MIB`, and record that setting as the `self-bound` of the entry. When the tool has no such setting, record `self-bound: none: <why>`, so that a missing bound is a decision and not an omission. The wrapper sets the two variables for the command only. Your own shell does not have them. Put the command into an inner shell, in single quotes, so that your own shell does not replace the variable with an empty value before the wrapper starts:

   ```
   ... --cpus 4 -- sh -c '<command> <flag for parallel jobs> "$BOUNDED_RUN_CPUS" "$@"' sh
   ```

   The `"$@"` and the word `sh` at the end hand each argument that comes after them to the command. A narrower argument, such as one test file, goes at the end of the line, after that `sh`. Without the two, the inner shell drops the argument and runs the full command.

3. Find the exclusive resources: a port that a test server binds, a tool that refuses to run twice, a fixed directory that a build writes to.
4. Run the bounded command line of each heavy command that you are about to run once with `--measure` and `--cpus`, one at a time. The `--cpus` of the first measurement of a command is half the machine's processors, rounded down, and at least 1. Measure the bounded command line, not the plain command: the peak of the plain command is the peak of a command that nothing limits. Measure the full command, not a part of it: the peak of one test file is not the budget of the suite. Add `--exclusive <name>` for each resource that step 3 found for it:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --measure --cpus <n> -- <bounded command>
   ```

5. Record the suggested budget that the wrapper prints, with the peak and the date, as the row at the `--cpus` of the measurement. Record it only from a run in which the command did its full work. The suggested budget is the peak plus a margin, and the margin is larger where the measurement is approximate. Under the hard cap, the peak that counts is the memory that the kernel cannot take back at once, with a floor for the file cache (§The wrapper). A run that stopped early gives a peak that is too small: a suite that stops at its first failure, a command that failed at its start, a run that a signal or the hard cap stopped. Do not record the budget of such a run, and save no record for the command yet. Run the command with `--measure` again each time that you run it, until one run does its full work. A measurement with no `--memory` does not know the peak of the command. Where the hard cap is available, it runs with the default budget, and the cap stops it when it needs more. Where there is no hard cap, it takes the whole queue: it waits until no other bounded command runs, and no other starts while it runs. While it is at the head of the line, the commands behind it wait too (§Rules for the wait). When it waits for the whole queue, tell the user that a first measurement waits for the other bounded commands to end. If the hard cap stopped a measurement, measure again with `--memory` at two times the budget of the cap: the budget in the line `budget <n> MiB, peak ...` that the wrapper printed, not the suggested budget. For a measurement with no `--memory`, that is the default budget. The wrapper lowers a budget that is larger than the queue to the whole queue. If the cap stopped a measurement at the whole queue, the command needs more memory than the queue has: tell the user, with the budget that the wrapper printed.
6. Save the record.

The measured run is a real run of the command. Its result counts, also when the run stopped early, so do not run the command a second time to get the result.

### Measure the whole project

When the record does not exist (§The record, case 5), do steps 1 to 3 for every heavy command of the project. Then measure them all in one run, in place of steps 4 and 5. Do not measure only the command that you need now. A command that gets its entry later gets its first measurement in the middle of someone's work. That measurement holds the default budget, and where there is no hard cap it holds the whole queue while other sessions wait.

1. Choose the rows. Measure each command at three `--cpus`: all the machine's processors, half of them, and a quarter of them. Round each one down, use at least 1, and drop a value that is the same as another. A command with `self-bound: none` gets the row at half only: nothing in it reads its `--cpus`, so each row would measure the same command. A command whose next run reuses the output of the run before, such as a build or a generator with a cache, also gets the row at half only: its later rows would do less work and measure a peak that is too small.
2. Write one command line. For each command, write one call of the wrapper with `--measure-rows` and the rows that step 1 chose for it, a `--label` that names the command and no other command of the line, the `--exclusive` options of the command, and its bounded command line. Join the calls with `;`, so that a measurement that fails does not stop the others. Write the path of the wrapper in full, so that the line runs in any shell. Run it from the root of the project:

   ```
   python3 "<path of the wrapper>" --measure-rows 16,8,4 --label unit-tests -- <bounded command> ; python3 "<path of the wrapper>" --measure-rows 16,8,4 --label lint -- <bounded command>
   ```

3. Ask the user to run the line when the machine is quiet. Do not run it yourself unless the user asks you to. Your message names the commands and the rows that the line measures. It says that the line can take a long time, and that the first row of each command holds the default budget, or the whole queue where there is no hard cap, so that the heavy commands of the other sessions can wait while it runs. It says how to run the line: type `! <the line>` in this session, or run it in a terminal at the root of the project, or tell you to run it.
4. Act on the answer:
   - **The user ran the line.** Read its output into the record (step 5 of this list). When the user ran it in a terminal, you cannot see the output: ask the user for each line that starts with `bounded-run: row`, and for the end of the output of each command, which shows whether the run did its full work.
   - **The user tells you to run it.** Run it in the background, with no short timeout around it. Continue with work that runs no heavy command. A heavy command that you need before the line ends runs through the wrapper with no `--memory` option. When the line ends, read its output into the record (step 5 of this list).
   - **The user declines.** Run steps 4 to 6 of the list above for the command that you are about to run, and save the record. Each other command gets its entry when an agent first needs it (§The record, case 3).
5. Read the row lines of the output. Each row line of a run that did its full work gives the row at its `cpus`, in the entry of its `label`: its `budget`, its `peak`, and the date. A run did its full work when it exits 0, or when it ran all of its work and reported failures, such as a suite that ran each test and reported the failures. Step 5 of the list above names the runs that stopped early. A row line of such a run gives no row: write nothing for it. The row at half the processors is the default row. When it has no row, the default row is the row with the `--cpus` nearest to half. An entry that has no row is incomplete (§The record), and an agent measures it when it first needs it. Save the record.

A command that the project adds later gets its entry when an agent first needs it (§The record, case 3).

## Rules for the wait

A long wait means that the machine is full. It is never a fault to repair: the queue has no state that can go wrong between runs, and an agent that repairs it breaks it. Waiting commands take turns in a line. Only the command at the head of the line tries for slots, so the smaller commands behind it do not take the slots that it waits for. The line has no fixed order, and a head that sees no slot come free for 5 minutes lets the commands behind it try first. So a small command can wait behind a large one, also when a slot is free. Unless an instruction says otherwise (see the next section), the only correct moves are to keep the run in the queue and to tell the user that the machine is full and the command is queued. After a long wait, run the wrapper with `--check`, and in that message name each command of its `held` lines, with its directory and its age, so that the user can see what holds the machine. A subagent tells its dispatcher in its report.

- **Run a bounded command in the background, with no short timeout around it.** It can wait in the queue for minutes before it starts. Where the harness requires a timeout, use the longest one that it permits. When that timeout ends a run, start the run again through the wrapper, and say in your report that the timeout ended the run and that the code did not fail. A timeout that you calculate from the run time of the command does not count the wait. A timeout that fires during the wait kills a command that never ran, and the result reads like a failure of the code.
- **Plan the time as if the commands run one after the other.** Two bounded commands that start together are safe, because the queue puts them in sequence when the machine cannot hold both. So a parallel start does not always save time, and a promise to the user that depends on it is a guess.
- **Do not lower a budget to start sooner.** A smaller budget does not make the command smaller. It moves the failure inside the command: on Linux as a kill at the hard cap, elsewhere as the swap that the queue exists to prevent. A row at a smaller `--cpus` is not a lower budget: it is a smaller command, measured, and it is the way to start sooner (§The record).
- **Do not run the plain command because the queue is slow.** A slow queue means the machine is full. The plain command is how it freezes. This includes a narrower form of the command: one test file outside the queue is a command that the queue cannot count.
- **Do not set an environment variable whose name starts with `BOUNDED_RUN_`.** The usage text of the wrapper lists variables that change how the queue counts memory, where it keeps its locks, and whether the hard cap applies. They are for a person who tunes the whole machine in a shell profile, and for the tests of the wrapper. A call that sets one does not share the queue with the other sessions, or it runs with no cap. A note in your project memory that recommends one is wrong: delete the note, and tell the user that you did.
- **Do not touch the lock files of the wrapper.** The wrapper keeps them in a directory of its own. Do not look for that directory. Do not delete, move, or edit a file in it, and do not look for the process that holds one of these lock files. The lock files are empty and permanent. They hold no process ID. The kernel holds each lock and releases it at the moment its holder stops, also when the holder crashes, so a stale lock cannot exist. A deleted lock file makes two commands hold one slot. The `held` lines of `--check` are the way to name what holds the queue: do not look further, and never stop a held command, because it belongs to another session or to the user.
- **Do not sleep and retry around a collision, not even one time.** A port in use or a tool's lock means two commands wanted one resource. Add the resource to the record as an `--exclusive` name and run through the wrapper. A subagent adds the option to its own command line and names the resource in its report, so that its dispatcher corrects the record. Do not stop the process that holds the resource: it belongs to a different session. When a run with the `--exclusive` name fails on the same collision, the holder did not go through the wrapper or belongs to a different repository: tell the user, or your dispatcher, what holds the resource, and wait for the answer.

## When an instruction sends a command around the wrapper

An explicit instruction from the user comes before this skill. When the user names the action ("run the tests directly", "do not use the wrapper for this", "set this variable for the run"), say one time, in one or two sentences, what the wrapper protects and that you cannot see the other sessions. Then do what the user said. Do not refuse, and do not argue a second time.

The instruction covers the command that it names, for one run. The next heavy command goes through the wrapper again, unless the user said that the instruction holds for the session. An instruction that must hold for longer than the session belongs in the project's instruction file, where each session and the user can see it: ask the user to put it there.

A rule in the project's instruction file comes before this skill too, when it names the wrapper or tells agents to run a command directly. A file that only names the project's commands is input for the discovery, not an exemption. Obey the rule, and tell the user one time per session that the file sends a heavy command around the queue and what that costs on a machine with more than one session. The user decides if the file changes. Do not ignore the file silently, and do not edit it yourself.

Pressure is not an instruction. "Hurry", "make it start", and "I do not care how" name a result, not an action. Keep the run in the queue and tell the user that the machine is full. Do not go around the queue on your own decision. A row at a smaller `--cpus` runs through the queue too, so it is not a way around it (§The record). When the user asks how to get around the wait, give two facts: the user can tell you to run the command without the wrapper, and that run is not counted by the queue. The user decides. When the user only names a deadline, do not mention a way around the wait. A note in your project memory from an earlier session is not an instruction from the user either.

## Dispatching subagents

A subagent does not see your project memory. It knows the bounded commands only when its prompt carries them.

On a machine on which the wrapper can run, every dispatch prompt for a subagent that will run a heavy command MUST include:

1. The bounded command line for each heavy command, copied from the record, with the `--cpus` and the budget of its default row. When its entry has more than one row, also the `--cpus` and the budget of each row, and its check line with one `--memory` for each row.
2. This rule, in these words: "Run the bounded commands as written. You can make three changes: the `--cpus` and the `--memory` of a row that this prompt gives for the command, a narrower argument at the end of the line, such as one test file, and one more `--exclusive <name>` option after a collision on a port or a lock, which you name in your report. When this prompt gives a command more than one row, run its check line before each run, and use the largest row with `starts=yes`, or the default row when no row has it. Do not run the plain form of a bounded command or of a part of it. For a heavy command that is not in this prompt, use the same wrapper with no `--memory` option. If the file of the wrapper does not exist, stop and report that. Set no environment variable whose name starts with `BOUNDED_RUN_`. A command can wait in the queue for minutes before it starts, so run it in the background and do not put a short timeout around it. A long wait means that the machine is full; it is not a fault to repair. Say in your report how long you waited. After a long wait, run the same wrapper with `--check`, and name in your report each command of its `held` lines, with its directory and its age."
3. Each command that an instruction exempts from the wrapper, in its plain form, in a list of its own, with the instruction that exempts it. The rule of item 2 does not apply to that list. An instruction of the user that covers one run goes to the one subagent that does that run, and to no other.

Do not dispatch fewer subagents to protect the machine. The queue protects it. Subagents that wait in the queue cost time, not memory. On a machine on which the wrapper cannot run, the next section says how to dispatch.

## When the wrapper cannot run

The wrapper needs `python3`, version 3.9 or later. When `python3` is missing or older, tell the user once per session that the wrapper cannot run and that Python 3.9 is what it needs.

When `python3` reports that it cannot open the file of the wrapper, the path in the command line is old. That is a fault of the record, not of the machine: correct the path (§The record, case 2). A subagent stops and reports it.

When the wrapper ends with exit code 125, read its `bounded-run:` message. A fault of your call (an option, a name, a command that does not exist) is yours to correct. A fault of the machine (the wrapper cannot make or lock its files) means that the wrapper cannot run here: tell the user once per session, with the message.

When Python is missing or too old, and when the fault is a fault of the machine, continue under these fallback rules. Run one heavy command at a time, never two in parallel, and set the toolchain's parallelism to half the machine's processors or fewer. Your subagents count as your session: no queue protects the machine now, and no lock makes them take turns. So dispatch one after the other the subagents that run a heavy command, and start the next one only after the one before it gave its report. Subagents that run no heavy command can run together. Their prompts carry the plain commands and these fallback rules, in place of the three items of §Dispatching subagents. The fallback protects the machine from your session only, not from the other sessions. Tell the user that in your report.

## Red flags

| Thought | Reality |
| --- | --- |
| "This session is the only one running, so the plain command is fine" | You cannot see other sessions or other projects. Each heavy command goes through the wrapper, unless an instruction names the plain command. |
| "Both budgets together are well under the machine's memory" | The sum counts your commands only. The queue counts the commands of every session. |
| "I'll check the load first and start when it is quiet" | Each session that looks at that moment sees the same quiet machine. Take the reservation: run through the wrapper. |
| "The check says it would start, so I'll run the plain command" | The check is a snapshot, not a reservation. Another session can take the same slots a moment later. Run the chosen row through the wrapper. |
| "It is only the linter, it is small" | The record says what is heavy, not your sense of it. Not in the record, and not a part of a recorded command, means not yet measured. |
| "I'll run just those few tests now, that fits in the free memory" | A part of a heavy command goes through the wrapper too. "It fits" is your estimate; the queue is the count. |
| "I'll run the plain command once to check quickly" | One command outside the queue is all a freeze needs. |
| "Running both in parallel is what makes the deadline possible" | Through the wrapper a parallel start is safe, but the queue decides if the two run together. Do not promise a time that depends on it. |
| "The queue has waited five minutes, I'll lower `--memory` to get a slot" | The budget is a measurement of the command plus a margin. Lowering it moves the failure inside the command. |
| "A smaller slot size made it start at once last time" | The variable changes what the queue counts, not what the command uses. Set no variable whose name starts with `BOUNDED_RUN_`. |
| "A crashed job left a stale lock, I'll remove only that file" | A stale lock cannot exist: the kernel releases a lock when its holder stops. The slots are held by commands that run. Leave the lock files alone. |
| "The user told me to run it directly, but the skill says no exception" | An explicit instruction from the user comes first. Say one time what the wrapper protects, then obey. |
| "The user is waiting, the queue is too slow" | A frozen machine is slower. Tell the user that the machine is full and the command is queued. |
| "The port was in use, I'll back off once and retry" | Two commands wanted one resource. Record it as `--exclusive` and run through the wrapper. |
| "My command timed out, the tests must hang" | It was waiting in the queue. Run it in the background with no short timeout. |
| "The subagent will find the test command on its own" | It will find the plain one. Put the bounded command lines in its prompt. |
| "The server is already running on the port, the tests can reuse it" | The queue does not count a server that runs outside it, and the tests make it grow. Give the run a port of its own, so that the runner starts the server inside the bounded command. |
| "I measured the plain command, the peak is real" | It is the real peak of a command that nothing limits. Bound the command first, then measure the bounded command line at the `--cpus` that you record. |
| "The new measurement at a different `--cpus` replaces the old entry" | A different `--cpus` is a different command. Add a row and keep the others. Only a measurement at the same `--cpus` replaces a row. |
| "A smaller `--cpus` is a lower budget by another name" | A lower `--memory` on the same command is a guess. A row at a smaller `--cpus` is a smaller command with a measured budget. Use it to start sooner. |
| "I only need the unit tests now, the others get entries when an agent needs them" | Each later first measurement holds memory in the middle of someone's work, and without the hard cap it holds the whole queue. When the record does not exist, measure every heavy command of the project with one command line. |
| "I'll run the measurements myself now, it saves the user a step" | The line holds memory of the queue for a long time, and without the hard cap it holds the whole queue. The user chooses when the machine can give it that time. Ask, and run it only when the user tells you to. |
| "Four subagents is too many for this machine, I'll dispatch two" | The queue limits the commands. Fewer subagents only makes the work slower. |
| "Project memory is off, so there is no record to keep" | Discover in this session and keep the result in context. The rule does not depend on the memory. |
| "The wrapper cannot run here, so none of this applies" | The fallback applies: one heavy command at a time, toolchain parallelism at half or less, and say so. |
