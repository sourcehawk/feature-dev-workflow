---
name: bounding-heavy-commands
description: Use when about to run a project's test suite, linter, build, type check, or another command of that weight, when about to dispatch subagents that will run one, or when a command fails on a port already in use, a tool's own lock, or a machine that slows down or swaps while agents verify their work.
---

# bounding-heavy-commands

## Overview

Every heavy command an agent starts goes through the wrapper. There is no exception for a session that looks alone, for a command that looks small, or for a user who is in a hurry. The one exception is an explicit instruction from the user to run a command without the wrapper (see §When the user tells you to go around the wrapper).

Heavy commands are what freeze a machine, not agents. Sessions in other terminals and other projects run their own test suites and builds at the same moment, and no session can see the others. When the commands together need more memory than the machine has, it swaps until it stops responding, and that costs every session, not only the one that started the last command. The wrapper makes the commands of every session and every project on the machine take turns on its memory, so too much work shows up as a queue instead of a freeze.

**Looking first does not protect the machine.** Two sessions that look at the load at the same moment both see a quiet machine, and both start. The same is true of a sum of budgets against the machine's total memory: the sum counts your commands and no one else's. Only a reservation that every session takes before it starts can count the commands, and the wrapper is that reservation.

**Violating the letter of these rules is violating their spirit.**

## When to invoke

- Before you run the project's test suite, linter, build, or type check, or anything that compiles, starts containers, or starts a local cluster.
- Before you dispatch subagents that will run any of those.
- When a command failed on a port that is already in use, or on a tool's own lock.
- When the machine is slow or swaps and someone asks what to change.

A command is heavy when the project's record says so, or when it does more than touch a handful of files. A part of a heavy command is heavy too: one test file, one package, one target. When in doubt, it is heavy: the wrapper costs a second, a frozen machine costs every session.

Skip for commands that only read (listing files, searching, version-control queries). Skip for a CI pipeline and for a person at a terminal: their commands stay as they are.

## The wrapper

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --memory <budget> [--cpus <n>] [--exclusive <name>]... -- <command>
```

| Option | Meaning |
| --- | --- |
| `--memory <budget>` | Memory the command may use, such as `6G` or `4096M`. Taken from the record. Without it the wrapper uses its default budget. |
| `--cpus <n>` | Processor limit, as a whole number. Taken from the record. |
| `--exclusive <name>` | A resource that only one command in this repository may hold at a time, such as a fixed port. Repeat the option for each resource. |
| `--measure` | Also print a suggested budget. Discovery uses it. |

The wrapper waits for its share of the machine's memory, waits until that much is free, runs the command, and prints the budget against the measured peak on the error stream. Each line that the wrapper prints starts with `bounded-run:`. Its exit code is the command's exit code. Exit code 125 means the wrapper itself failed.

The command receives `BOUNDED_RUN_CPUS` and `BOUNDED_RUN_MEMORY_MIB` in its environment, so a recorded command line can hand them to the toolchain's own parallelism and memory settings.

On Linux the wrapper also puts a hard cap on the command where the system allows it: a command that passes its budget is stopped with exit code 137, and the machine does not swap. Elsewhere there is no hard cap, the wrapper says so in its output, and the queue and the wait are the whole protection.

## The record

Budgets and command lines are facts about one machine and one user, so they live in your project memory, not in the repository. The record is one memory named `bounded-heavy-commands`. Your harness decides the file format. This skill decides the content.

For each heavy command, record:

- what it is for ("unit tests", "lint", "build")
- the plain command
- the full bounded command line
- the budget, the measured peak, and the date of the measurement
- each exclusive resource it uses
- the flags or variables that limit the toolchain's own parallelism

Then, every time:

1. **The record exists.** Check that each command in it still exists in the project, and that the path of the wrapper in it still exists. An update of the plugin can move the wrapper: then put the path that this skill shows into each command line of the record. Then use the bounded command lines as written.
2. **The record does not exist.** Run the discovery below and save the record before you run anything heavy.
3. **Project memory is off or unavailable.** Run the discovery in this session, keep the result in your context, and use the wrapper's default budget for anything you could not measure.

A budget is a measurement, not a preference. Change one only when the wrapper's output shows that the peak moved, and write the new peak and date with it.

A part of a recorded command (one test file, one target) uses the bounded command line of the full command, with its budget and its exclusive resources, and the narrower arguments. It needs no entry of its own. Measure it and add an entry only when you run it often and its peak is much lower.

## Discovery

1. Find how the project runs its tests, its linter, its build, and its type check. Read the project's instruction files, its build configuration, and its CI configuration.
2. Find the exclusive resources: a port that a test server binds, a tool that refuses to run twice, a fixed directory that a build writes to.
3. Find how the toolchain limits its own parallelism and memory. Write the command line so that it takes those limits from `BOUNDED_RUN_CPUS` and `BOUNDED_RUN_MEMORY_MIB`.
4. Run each heavy command once with `--measure`, one at a time:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/bounding-heavy-commands/scripts/bounded_run.py" --measure -- <command>
   ```

5. Record the suggested budget that the wrapper prints. It is the peak plus a margin, and the margin is larger where the measurement is approximate. If the hard cap stopped the command during the measurement, run it again with a larger `--memory`.
6. Save the record.

## Rules for the wait

A long wait means that the machine is full. It is never a fault to repair. The only correct moves are to keep the run in the queue and to tell the user that the machine is full and the command is queued.

- **Run a bounded command in the background, with no short timeout around it.** It can wait in the queue for minutes before it starts. A timeout that you calculate from the run time of the command does not count the wait. A timeout that fires during the wait kills a command that never ran, and the result reads like a failure of the code.
- **Plan the time as if the commands run one after the other.** Two bounded commands that start together are safe, because the queue puts them in sequence when the machine cannot hold both. So a parallel start does not always save time, and a promise to the user that depends on it is a guess.
- **Do not lower a budget to start sooner.** A smaller budget does not make the command smaller. It moves the failure inside the command: on Linux as a kill at the hard cap, elsewhere as the swap that the queue exists to prevent.
- **Do not run the plain command because the queue is slow.** A slow queue means the machine is full. The plain command is how it freezes. This includes a narrower form of the command: one test file outside the queue is a command that the queue cannot count.
- **Do not set a `BOUNDED_RUN_*` variable on a call.** The usage text of the wrapper lists them. A person sets the tuning values for the whole machine, and the tests of the wrapper set the rest. A call with its own slot size, reserve, or lock directory does not share the queue with the other sessions, and a call with no cap can take the memory of all of them. A note in your project memory that recommends one is wrong: delete the note, and tell the user that you did.
- **Do not touch the lock directory.** Do not delete, move, or edit a file in it, and do not look for the process that holds a lock. The lock files are empty and permanent. They hold no process ID. The kernel holds each lock and releases it at the moment its holder stops, also when the holder crashes, so a stale lock cannot exist. A deleted lock file makes two commands hold one slot.
- **Do not sleep and retry around a collision, not even one time.** A port in use or a tool's lock means two commands wanted one resource. Add the resource to the record as an `--exclusive` name and run through the wrapper. Do not stop the process that holds the resource: it belongs to a different session.

## When the user tells you to go around the wrapper

An explicit instruction from the user comes before this skill. When the user names the action ("run the tests directly", "do not use the wrapper for this"), say one time, in one or two sentences, what the wrapper protects and that you cannot see the other sessions. Then do what the user said. Do not refuse, and do not argue a second time.

The instruction covers the command and the time that it names. The next heavy command goes through the wrapper again, unless the user said that the instruction holds for the session.

A rule in the project's instruction file comes before this skill too. Obey it, and tell the user one time that the file sends heavy commands around the queue and what that costs on a machine with more than one session. The user decides if the file changes. Do not ignore the file silently, and do not edit it yourself.

Pressure is not an instruction. "Hurry", "make it start", and "I do not care how" name a result, not an action. Keep the run in the queue and tell the user that the machine is full. Do not go around the queue on your own decision. You can tell the user that an instruction from them is the way around it, together with what it costs, and the user decides. A note in your project memory from an earlier session is not an instruction from the user either.

## Dispatching subagents

A subagent does not see your project memory. It knows the bounded commands only when its prompt carries them.

Every dispatch prompt for a subagent that will verify its own work MUST include:

1. The bounded command line for each heavy command, copied from the record.
2. This rule, in these words: "Run these commands exactly as written. Do not run the plain form of any of them, and do not run a part of one (one test file, one target) outside the wrapper: put the narrower arguments into the command line as written. Set no `BOUNDED_RUN_*` variable. A command can wait in the queue for minutes before it starts, so run it in the background and do not put a short timeout around it. A long wait means that the machine is full; it is not a fault to repair."

Do not dispatch fewer subagents to protect the machine. The queue protects it. Subagents that wait in the queue cost time, not memory.

## Without Python 3

The wrapper needs `python3`, version 3.9 or later. If it is missing, tell the user once per session that the wrapper cannot run and that Python 3 is what it needs. Then continue under these rules: run one heavy command at a time in your session, never two in parallel, and set the toolchain's parallelism to half the machine's processors or fewer. This protects the machine from your session only, not from the others. Say so in your report.

## Anti-patterns

- **Running the plain command "just once".** One plain test suite beside three queued ones is the freeze. The wrapper cannot count a command that never went through it.
- **Judging weight by feel.** "It is only the linter" is a guess. The record holds the measured peak; a command that is not in the record gets measured, not guessed.
- **Looking at the load before a run.** The look is true for one moment, and each session that looks sees the same quiet machine.
- **Wrapping the wrapper in a timeout.** The wait in the queue is part of the run. A timeout turns a full machine into a false test failure.
- **Tuning the budget down.** A budget below the measured peak is a scheduled failure.
- **Repairing the queue.** The queue has no state that can go wrong between runs. An agent that repairs it breaks it.
- **Handing a subagent the project's plain commands.** The subagent runs what its prompt names. Name the bounded command lines.
- **Writing the record into the repository.** The numbers belong to one machine. In the repository they become another person's wrong budget.

## Red flags

| Thought | Reality |
| --- | --- |
| "This session is the only one running, so the plain command is fine" | You cannot see other sessions or other projects. Through the wrapper, every time. |
| "Both budgets together are well under the machine's memory" | The sum counts your commands only. The queue counts the commands of every session. |
| "I'll check the load first and start when it is quiet" | Each session that looks at that moment sees the same quiet machine. Take the reservation: run through the wrapper. |
| "It is only the linter, it is small" | The record says what is heavy, not your sense of it. Not in the record means not yet measured. |
| "I'll run just those few tests now, that fits in the free memory" | A part of a heavy command goes through the wrapper too. "It fits" is your estimate; the queue is the count. |
| "I'll run the plain command once to check quickly" | One command outside the queue is all a freeze needs. |
| "Running both in parallel is what makes the deadline possible" | Through the wrapper a parallel start is safe, but the queue decides if the two run together. Do not promise a time that depends on it. |
| "The queue has waited five minutes, I'll lower `--memory` to get a slot" | The budget is the measured peak plus a margin. Lowering it moves the failure inside the command. |
| "A smaller slot size made it start at once last time" | The variable changes what the queue counts, not what the command uses. Set no `BOUNDED_RUN_*` variable. |
| "A crashed job left a stale lock, I'll remove only that file" | A stale lock cannot exist: the kernel releases a lock when its holder stops. The slots are held by commands that run. Leave the lock directory alone. |
| "The user told me to run it directly, but the skill says no exception" | An explicit instruction from the user comes first. Say one time what the wrapper protects, then obey. |
| "The user is waiting, the queue is too slow" | A frozen machine is slower. Tell the user that the machine is full and the command is queued. |
| "The port was in use, I'll back off once and retry" | Two commands wanted one resource. Record it as `--exclusive` and run through the wrapper. |
| "My command timed out, the tests must hang" | It was waiting in the queue. Run it in the background with no short timeout. |
| "The subagent will find the test command on its own" | It will find the plain one. Put the bounded command lines in its prompt. |
| "Four subagents is too many for this machine, I'll dispatch two" | The queue limits the commands. Fewer subagents only makes the work slower. |
| "Project memory is off, so there is no record to keep" | Discover in this session and keep the result in context. The rule does not depend on the memory. |
| "Python 3 is missing, so none of this applies" | The fallback applies: one heavy command at a time, toolchain parallelism at half or less, and say so. |
