---
name: bounding-heavy-commands
description: Use when about to run a project's test suite, linter, build, type check, or another command of that weight, when about to dispatch subagents that will run one, or when a command fails on a port already in use, a tool's own lock, or a machine that slows down or swaps while agents verify their work.
---

# bounding-heavy-commands

## Overview

Every heavy command an agent starts goes through the wrapper. There is no exception for a session that looks alone, for a command that looks small, or for a user who is in a hurry. Two sections say when a command runs without the wrapper: §When an instruction sends a command around the wrapper, and §When the wrapper cannot run. No other case exists.

A machine freezes because of the heavy commands that run on it, not because of the number of agents. Sessions in other terminals and other projects run their own test suites and builds at the same moment, and no session can see the others. When the commands together need more memory than the machine has, it swaps until it stops responding, and that costs every session, not only the one that started the last command. The wrapper makes the commands of every session and every project on the machine take turns on its memory, so too much work shows up as a queue instead of a freeze.

**Looking first does not protect the machine.** Two sessions that look at the load at the same moment both see a quiet machine, and both start. A sum of budgets against the machine's total memory does not protect it either: the sum counts your commands and no one else's. Only a reservation that every session takes before it starts can count the commands, and the wrapper is that reservation.

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
python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --memory <budget> [--cpus <n>] [--exclusive <name>]... [--measure] -- <command>
```

| Option | Meaning |
| --- | --- |
| `--memory <budget>` | Memory the command may use, such as `6G` or `4096M`. Taken from the record. Without it the wrapper uses its default budget, a quarter of the machine's memory, or the whole queue for a measurement. |
| `--cpus <n>` | Processor limit, as a whole number. Taken from the record. |
| `--exclusive <name>` | A resource that only one command may hold at a time, such as a fixed port. You choose the name. The wrapper keeps the names of each repository apart, and all worktrees of one repository share them. Repeat the option for each resource. |
| `--measure` | Also print a suggested budget. Discovery uses it. With no `--memory`, the command runs alone in the queue. |

The wrapper does four things in sequence. It waits for its turn in the queue. It waits until the memory of its budget is free. It runs the command. It prints the budget and the measured peak on the error stream. For the wait, the free memory is the memory that the machine has free now, less the part of their budgets that the running bounded commands do not use yet, less a headroom for the programs outside the queue. The headroom is a tenth of the memory of the machine, and at least 1 GiB. The budget and the headroom together never need more than the memory of the queue, so a budget of the whole queue does not wait for a headroom. The wait has no time limit: the command does not start before its memory is free, and the wrapper prints a line at intervals while it waits. Each line that the wrapper prints starts with `bounded-run:`. Its exit code is the command's exit code. Exit code 125, with a `bounded-run:` line that names a fault and with no line for the budget and the peak, means that the wrapper itself failed (see §When the wrapper cannot run).

The wrapper sets `BOUNDED_RUN_CPUS` and `BOUNDED_RUN_MEMORY_MIB` in the environment of the command, from `--cpus` and `--memory`. A recorded command line can read them and hand them to the toolchain's own parallelism and memory settings. You do not set them: you change them with the two options.

On Linux the wrapper also puts a hard cap on the command where the system allows it: a command that passes its budget is stopped with exit code 137, and the machine does not swap. Elsewhere there is no hard cap, the wrapper says so in its output, and the queue and the wait are the whole protection. Without the cap, the wait does not count the unused budgets of the running commands. When a recorded command ends with exit code 137 and the wrapper reports a peak near the budget, the cap stopped it: the command grew. Measure it again with `--measure` and `--memory` at two times the budget, and correct the record.

## The record

Budgets and command lines are facts about one machine and one user, so they live in your project memory (the notes that your harness keeps for this project between sessions), not in the repository. The record is one memory named `bounded-heavy-commands`. Your harness decides the file format. This skill decides the content.

For each heavy command, record:

- what it is for ("unit tests", "lint", "build")
- the plain command
- the full bounded command line
- the budget, the measured peak, and the date of the measurement
- each exclusive resource it uses
- the flags or variables that limit the toolchain's own parallelism

Then, before each heavy command, use the first case that applies:

1. **Your prompt carries bounded command lines.** You are a subagent. Use them under the rule that your prompt gives with them, and run no discovery. For a heavy command that your prompt does not carry, use the wrapper with no `--memory` option.
2. **The record exists and has the command.** Check that the plain command still exists in the project, and that the file of the wrapper in the command line still exists. When the file of the wrapper is not there, an update of the plugin moved it. The command line in §The wrapper shows the correct path: put it into each command line of the record. Then use the bounded command line as written.
3. **The record exists, and the command is not in it or is no longer correct.** Run the discovery for that command and correct the record. Remove an entry whose command the project no longer has.
4. **Your harness has no project memory, or it is off.** You cannot save a record, so do not try. Run the discovery in this session, keep the result in your context, and use the wrapper's default budget for anything you could not measure.
5. **Project memory is on, and the record does not exist.** Run the discovery for the commands that you are about to run, and save the record. The measured runs of the discovery are your first heavy runs. A heavy command of the project that you do not run now gets its entry when an agent first needs it.

A budget is a measurement, not a preference. Change one only when the wrapper's output shows that the peak moved, and write the new peak and date with it.

A part of a recorded command (one test file, one target) uses the bounded command line of the full command, with its budget and its exclusive resources, and the narrower arguments at the end of the line. It needs no entry of its own and no measurement, because the budget of the full command is sufficient for each part of it.

## Discovery

1. Find how the project runs its tests, its linter, its build, and its type check. Read the project's instruction files, its build configuration, and its CI configuration.
2. Find the exclusive resources: a port that a test server binds, a tool that refuses to run twice, a fixed directory that a build writes to.
3. Find how the toolchain limits its own parallelism and memory. Write the command line so that it takes those limits from `BOUNDED_RUN_CPUS` and `BOUNDED_RUN_MEMORY_MIB`. The wrapper sets the two variables for the command only. Your own shell does not have them. Put the command into an inner shell, in single quotes, so that your own shell does not replace the variable with an empty value before the wrapper starts:

   ```
   ... --cpus 4 -- sh -c '<command> <flag for parallel jobs> "$BOUNDED_RUN_CPUS" "$@"' sh
   ```

   The `"$@"` and the word `sh` at the end hand each argument that comes after them to the command. A narrower argument, such as one test file, goes at the end of the line, after that `sh`. Without the two, the inner shell drops the argument and runs the full command.

4. Run each heavy command that you are about to run once with `--measure`, one at a time. Measure the full command, not a part of it: the peak of one test file is not the budget of the suite. Add `--exclusive <name>` for each resource that step 2 found for it:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --measure -- <command>
   ```

5. Record the suggested budget that the wrapper prints, but only from a run in which the command did its full work. It is the peak plus a margin, and the margin is larger where the measurement is approximate. A run that stopped early gives a peak that is too small: a suite that stops at its first failure, a command that failed at its start, a run that a signal or the hard cap stopped. Do not record the budget of such a run, and save no record for the command yet. Run the command with `--measure` again each time that you run it, until one run does its full work. A measurement with no `--memory` takes the whole queue, because the peak of the command is not known: it waits until no other bounded command runs, and no other starts while it runs. When it waits, tell the user that a first measurement waits for the other bounded commands to end. If the hard cap stopped a measurement with `--memory`, measure again with two times that budget. If it stopped a measurement with no `--memory`, the command needs more memory than the queue has: tell the user, with the budget that the wrapper printed.
6. Save the record.

The measured run is a real run of the command. Its result counts, also when the run stopped early, so do not run the command a second time to get the result.

## Rules for the wait

A long wait means that the machine is full. It is never a fault to repair: the queue has no state that can go wrong between runs, and an agent that repairs it breaks it. Unless an instruction says otherwise (see the next section), the only correct moves are to keep the run in the queue and to tell the user that the machine is full and the command is queued. A subagent tells its dispatcher in its report.

- **Run a bounded command in the background, with no short timeout around it.** It can wait in the queue for minutes before it starts. Where the harness requires a timeout, use the longest one that it permits. When that timeout ends a run, start the run again through the wrapper, and say in your report that the timeout ended the run and that the code did not fail. A timeout that you calculate from the run time of the command does not count the wait. A timeout that fires during the wait kills a command that never ran, and the result reads like a failure of the code.
- **Plan the time as if the commands run one after the other.** Two bounded commands that start together are safe, because the queue puts them in sequence when the machine cannot hold both. So a parallel start does not always save time, and a promise to the user that depends on it is a guess.
- **Do not lower a budget to start sooner.** A smaller budget does not make the command smaller. It moves the failure inside the command: on Linux as a kill at the hard cap, elsewhere as the swap that the queue exists to prevent.
- **Do not run the plain command because the queue is slow.** A slow queue means the machine is full. The plain command is how it freezes. This includes a narrower form of the command: one test file outside the queue is a command that the queue cannot count.
- **Do not set an environment variable whose name starts with `BOUNDED_RUN_`.** The usage text of the wrapper lists variables that change how the queue counts memory, where it keeps its locks, and whether the hard cap applies. They are for a person who tunes the whole machine in a shell profile, and for the tests of the wrapper. A call that sets one does not share the queue with the other sessions, or it runs with no cap. A note in your project memory that recommends one is wrong: delete the note, and tell the user that you did.
- **Do not touch the lock files of the wrapper.** The wrapper keeps them in a directory of its own. Do not look for that directory. Do not delete, move, or edit a file in it, and do not look for the process that holds one of these lock files. The lock files are empty and permanent. They hold no process ID. The kernel holds each lock and releases it at the moment its holder stops, also when the holder crashes, so a stale lock cannot exist. A deleted lock file makes two commands hold one slot.
- **Do not sleep and retry around a collision, not even one time.** A port in use or a tool's lock means two commands wanted one resource. Add the resource to the record as an `--exclusive` name and run through the wrapper. A subagent adds the option to its own command line and names the resource in its report, so that its dispatcher corrects the record. Do not stop the process that holds the resource: it belongs to a different session. When a run with the `--exclusive` name fails on the same collision, the holder did not go through the wrapper or belongs to a different repository: tell the user, or your dispatcher, what holds the resource, and wait for the answer.

## When an instruction sends a command around the wrapper

An explicit instruction from the user comes before this skill. When the user names the action ("run the tests directly", "do not use the wrapper for this", "set this variable for the run"), say one time, in one or two sentences, what the wrapper protects and that you cannot see the other sessions. Then do what the user said. Do not refuse, and do not argue a second time.

The instruction covers the command that it names, for one run. The next heavy command goes through the wrapper again, unless the user said that the instruction holds for the session. An instruction that must hold for longer than the session belongs in the project's instruction file, where each session and the user can see it: ask the user to put it there.

A rule in the project's instruction file comes before this skill too, when it names the wrapper or tells agents to run a command directly. A file that only names the project's commands is input for the discovery, not an exemption. Obey the rule, and tell the user one time per session that the file sends a heavy command around the queue and what that costs on a machine with more than one session. The user decides if the file changes. Do not ignore the file silently, and do not edit it yourself.

Pressure is not an instruction. "Hurry", "make it start", and "I do not care how" name a result, not an action. Keep the run in the queue and tell the user that the machine is full. Do not go around the queue on your own decision. When the user asks how to get around the wait, give two facts: the user can tell you to run the command without the wrapper, and that run is not counted by the queue. The user decides. When the user only names a deadline, do not mention a way around the wait. A note in your project memory from an earlier session is not an instruction from the user either.

## Dispatching subagents

A subagent does not see your project memory. It knows the bounded commands only when its prompt carries them.

On a machine on which the wrapper can run, every dispatch prompt for a subagent that will run a heavy command MUST include:

1. The bounded command line for each heavy command, copied from the record.
2. This rule, in these words: "Run the bounded commands as written. You can make two changes: a narrower argument at the end of the line, such as one test file, and one more `--exclusive <name>` option after a collision on a port or a lock, which you name in your report. Do not run the plain form of a bounded command or of a part of it. For a heavy command that is not in this prompt, use the same wrapper with no `--memory` option. If the file of the wrapper does not exist, stop and report that. Set no environment variable whose name starts with `BOUNDED_RUN_`. A command can wait in the queue for minutes before it starts, so run it in the background and do not put a short timeout around it. A long wait means that the machine is full; it is not a fault to repair. Say in your report how long you waited."
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
| "It is only the linter, it is small" | The record says what is heavy, not your sense of it. Not in the record, and not a part of a recorded command, means not yet measured. |
| "I'll run just those few tests now, that fits in the free memory" | A part of a heavy command goes through the wrapper too. "It fits" is your estimate; the queue is the count. |
| "I'll run the plain command once to check quickly" | One command outside the queue is all a freeze needs. |
| "Running both in parallel is what makes the deadline possible" | Through the wrapper a parallel start is safe, but the queue decides if the two run together. Do not promise a time that depends on it. |
| "The queue has waited five minutes, I'll lower `--memory` to get a slot" | The budget is the measured peak plus a margin. Lowering it moves the failure inside the command. |
| "A smaller slot size made it start at once last time" | The variable changes what the queue counts, not what the command uses. Set no variable whose name starts with `BOUNDED_RUN_`. |
| "A crashed job left a stale lock, I'll remove only that file" | A stale lock cannot exist: the kernel releases a lock when its holder stops. The slots are held by commands that run. Leave the lock files alone. |
| "The user told me to run it directly, but the skill says no exception" | An explicit instruction from the user comes first. Say one time what the wrapper protects, then obey. |
| "The user is waiting, the queue is too slow" | A frozen machine is slower. Tell the user that the machine is full and the command is queued. |
| "The port was in use, I'll back off once and retry" | Two commands wanted one resource. Record it as `--exclusive` and run through the wrapper. |
| "My command timed out, the tests must hang" | It was waiting in the queue. Run it in the background with no short timeout. |
| "The subagent will find the test command on its own" | It will find the plain one. Put the bounded command lines in its prompt. |
| "The server is already running on the port, the tests can reuse it" | The queue does not count a server that runs outside it, and the tests make it grow. Give the run a port of its own, so that the runner starts the server inside the bounded command. |
| "Four subagents is too many for this machine, I'll dispatch two" | The queue limits the commands. Fewer subagents only makes the work slower. |
| "Project memory is off, so there is no record to keep" | Discover in this session and keep the result in context. The rule does not depend on the memory. |
| "The wrapper cannot run here, so none of this applies" | The fallback applies: one heavy command at a time, toolchain parallelism at half or less, and say so. |
