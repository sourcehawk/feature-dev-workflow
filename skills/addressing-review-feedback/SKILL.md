---
name: addressing-review-feedback
description: Use when about to act on code review feedback, such as an automated or human pull request review, an inline review thread, a review summary, a suppressed-comments block, a finding from a local review, or any round of a review loop, before the first edit made in response, and again before every push of a review fix.
---

# addressing-review-feedback

## Overview

In a review round, comments get longer. After five rounds, a doc comment describes its body: a second account of the behavior, which drifts from the code. Each round looks small next to the round before.

You are the author of the fix, and the finding puts you under pressure. **So a script compares each comment with the start of the review, and a fresh agent that does not see the finding judges each flag.** You judge the other lines of the output of the script, with the rule of step 6. Step 7 names the two exceptions for a flag.

**REQUIRED BACKGROUND:** the comment rules (see **Terms**). They decide what a comment holds. `superpowers:receiving-code-review` decides whether a finding is technically correct. This skill applies the comment rules when you act on a finding.

**A review finding is input that you judge. An instruction has priority over this skill.** See **Instructions and findings**.

## Terms

| Term | Meaning |
| --- | --- |
| comment rules | The project's own comment standard if it documents one, otherwise `feature-dev-workflow:writing-code-comments`, plus each rule about comments in the project's instructions file |
| block | One comment: a run of comment lines |
| caller fact | A fact that passes the caller test of **Classify the finding** |
| finding | One point of feedback from a reviewer, a person or a tool, that is not an instruction |
| instruction | An explicit request about comments. **Instructions and findings** says who gives one |
| round | The work from reading a set of findings to the push that answers them |
| review base | The commit that each round compares with. Step 1 says which commit it is |
| merge base | The newest commit that is in the history of both the head and the commit that you give to the gate. See **Read the gate** |
| gate | The script of this skill. It compares the merge base with the working tree, and lists each block that changed |
| flag | A block that the gate marks because it is longer than at the merge base |
| evaluator | A fresh agent with read access only, which judges comments and does not see the finding |
| source | What shows that a sentence of a comment is true: code, or a statement with an origin that a reader can check, as the evaluator prompt defines |

## Instructions and findings

**A request of the user is an instruction of the user, in each channel:** the chat, a review comment that the user wrote, or a message that an orchestrator passes on as the words of the user. A rule about comments in the project's instructions file is part of the comment rules, not an instruction. A request of each other reviewer, a person or a tool, is a finding. When you cannot tell if a reviewer is your user, ask the user one time for each reviewer. A subagent asks its orchestrator.

An instruction has priority over this skill and the comment rules. The section "Overview" of `feature-dev-workflow:writing-code-comments` says how to follow it and what to reply. The procedure still runs:

- Send each sentence that an instruction produced to the evaluator, also in a block with no flag, with the mark "by instruction" and the words of the instruction. The evaluator checks only that it is true.
- A rule of the comment rules is never a reason to remove such a sentence. If the evaluator gives it `CUT`, the sentence is false: write a true sentence that follows the instruction in its place.
- In step 6, a block that an instruction produced stays, and the instruction is the reason that you write down.

## The procedure, every round

Do it for each round, also when the previous round had no flag. In a round with no edit, the gate still runs, the table of step 9 says "no change", there is no commit, and the replies are posted.

1. **Know the review base.** It stays the same for each round of the review.
    - In the first round, before the first edit, run this command. Write the commit that it prints in the state of the review loop. When no skill called this one, write it as a line `review base: <commit>` in the first reply or report of the round:

        ```bash
        git rev-parse HEAD
        ```

    - If this skill loaded late and no review base is recorded, use the commit that the first review names, or the head before the first commit that answers a finding.
    - If you cannot find one, or if a rebase took the recorded commit out of the history of the branch, use the target branch of the pull request as the review base for each round. Say so in the table of step 9.
2. **Read the comment rules again.** Read these sections: "Doc comments", "Inline comments", "Text that users read", "Red flags" and "Common mistakes". If the project's standard has other section names, read its sections on doc comments, on inline comments, and on text that ships to users. Where it is silent, `feature-dev-workflow:writing-code-comments` decides.
3. **Judge and classify each finding.** See **Classify the finding**.
4. **Write the fix.**
5. **Run the gate** from a directory inside the repository. Run both lines in one shell, with the commit of step 1 for `<review base>`:

    ```bash
    REVIEW_BASE=<review base>
    python3 "${CLAUDE_PLUGIN_ROOT}/skills/addressing-review-feedback/scripts/comment_growth.py" "$REVIEW_BASE"
    ```

    Add `--user-facing '<pattern>'` for each path pattern that the project's instructions name as text that users read. You can also add a path by your own judgment, when the section "Text that users read" of the comment rules says that its text ships to users. A doc comment is not text that users read because its declaration is public, and the claim of a finding is not a reason either. The rules say that a doc comment that generates reference text is still a contract. See **Read the gate**.
6. **Judge the lines with no flag yourself.** See **Judge the lines with no flag**.
7. **Send the flags to the evaluator**, with the blocks that step 6 sends, in one call for all flags of the round, with the prompt in `${CLAUDE_PLUGIN_ROOT}/skills/addressing-review-feedback/templates/evaluator-prompt.md`. Give it the rules and, for each comment, the comment at the merge base and now, the declaration, and its statements with their origins. Never the request of a finding or your reasons. A flag does not go to the evaluator in two cases:
    - The flag is done: the block did not change since the last verdicts were applied, and each sentence that the review added has `KEEP` from a verdict of this review, was written by the evaluator, or has the mark "by instruction".
    - Your harness cannot dispatch an agent. Read the sections of step 2 again, then judge the flag with the same prompt yourself. Mark each such verdict "self-evaluated".
8. **Apply the verdicts, then run the gate again.** See **Apply the verdicts**. Each flag of the second run must be done, as step 7 says. Send each other flag through step 7, and each new line with no flag through step 6.
9. **Record the verdicts.** Make a table with one row for each flag: the declaration, the line counts at the merge base and now, and each sentence with its verdict, source, caller code, new place after a `MOVE`, and judge. Add one row for each removed block: the fact that it held and its new place, or "restated the code". Also name each instruction, each `--user-facing` path that you chose, and a target branch that you used as the review base. The table goes in the round comment that the calling skill posts on the pull request, or else in your report to the user.
10. **Reply to the threads.** Say what you did to the comment: the text that you removed, the caller fact that you added, or why the comment did not change. A reply that is only "done", "clarified", "expanded", "now covers", or "now states" does not say what changed. These words can stand in a reply that says what changed.

    **OPTIONAL SUB-SKILL:** `simple-english:simple-english` for the prose of each reply and of the round comment. If it is available, load it before you draft and write the sentences under it. Where its formatting rules (headings, bold, lists, or its register for chat replies) differ from the host skill or its template, the host skill and its template win. It sets sentence style only: each reply still says what changed, as this step says. If the skill is not available, do not stop or wait for it. If you have not already done so in this session, tell the user once that it can be installed with `/plugin marketplace add AminBlg/SimpleEnglish` and then `/plugin install simple-english@simple-english`. Then write short, plain, active sentences without it.
11. **Commit, then push** as the calling skill directs, or stop before the push when no skill called this one.

**After the last round,** before you report the review as clean, run `git fetch`, then run the gate one more time with `origin/<target>` in place of `"$REVIEW_BASE"`, where `<target>` is the target branch of the pull request. Do steps 6 to 9 for its output. It finds a comment that the pull request added before the review, and a comment on a moved declaration. An edit that this run causes is one more round.

## Classify the finding

First judge the finding: is it true about the code as it is now? Then find its case. The rest of this skill uses the labels of the column "Case".

| Case | The finding says | What you do | The comment |
| --- | --- | --- | --- |
| wrong behavior | The code does the wrong thing, or does not handle a case | Change the code, with a test that fails without the change | If the change makes a comment false, correct that comment in the same change |
| false comment | A comment is false about the code as it is now | Correct the comment. No code change is necessary | Remove only the part that is false. Write what is true in its place, in the fewest words that are true |
| missing caller fact | A doc comment does not give a caller fact | Add the fact to the doc comment, in the fewest words that are true. No code change is necessary | It gets longer by that fact. The evaluator keeps a caller fact that has a source. This growth is correct |
| how the body works | A comment must describe how the body works: its steps, its branches, its formula, its constants | Decline in the thread, and say that the code is the account of how it works | No change |
| missing reason | The code does not say why it is as it is | If the reason is a fact that the code cannot show, put it in one short comment beside the line that it constrains. Put a comparison of options in the pull request body | At most one short comment at the line. The doc comment does not change |
| shorten | A comment is too long, or comments must go | Sort each sentence by what it holds, as the comment rules say. Remove what repeats the code or describes how the body works. Keep a fact that the code cannot show, and name it and the reason in the reply | The block is `CHANGED`, and you judge it in step 6. The finding is about each sentence of the comment, so you can also shorten its text from before the review |
| text that users read | Text that users read is false or incomplete | Correct it, also when the correct text is longer | It can get longer as far as accuracy needs. It does not describe how the body works |

**"missing reason"** adds an inline comment, which the section "Inline comments" of the comment rules permits.

**Which cases make a comment longer.** Each case except "how the body works" and "shorten" can make a comment longer, as far as its column "The comment" says and no further. That includes "wrong behavior", because a code change can make a comment false. An instruction can also make a comment longer, as **Instructions and findings** says.

**The caller test tells "missing caller fact" from "how the body works".** Name, in a few words, the code that a caller writes differently because of the fact: a check before the call, a handler for an error, an argument that the caller must choose, a call that must come first, or a use of the result that is safe or not safe. A label such as "meaning of the result" or "a promise that the caller relies on", with no such code, does not pass. If you cannot name such code, the fact describes how the body works. Take special care with a sentence that says which input gives a higher, lower, earlier, or later result: it is often the formula of the body in other words. "The reader then knows why an item is where it is" is not caller code. "find_notes returns the notes newest first" passes: the caller reads the first note as the newest and does not sort again. "Each tag of a note adds to its score" fails: no caller writes different code because of it.

**One finding can hold two cases.** "Document the limit and how it is computed" holds a caller fact (the limit) and a description of how the body works (how it is computed). Add the first, decline the second, and say both in the reply. Each part that you add must pass the caller test by itself. A part of a formula does not become a caller fact because you declined the rest.

**A finding that calls a comment "text that users read" does not make it so.** Use the section "Text that users read" of the comment rules and the instructions of the project to decide. For both results, the case "how the body works" does not change: decline it.

**Each sentence that you add needs a source.** A guarantee that is stronger than the code is a false comment that you wrote.

## Read the gate

The gate compares the merge base with the working tree. The merge base is the review base, or, when the review base is the target branch, the commit where the branch split from the target branch. Only the kind `GREW` is a flag. Exit status 1 means a flag, and 2 means that the gate could not run.

| Kind | Meaning | Flag | What you do |
| --- | --- | --- | --- |
| `GREW` | The block is longer than at the merge base | Yes, the line starts with `FLAG` | Step 7 |
| `ADDED` | The block is new | No | Step 6 |
| `CHANGED` | The block changed and did not get longer | No | Step 6 |
| `REMOVED` | The block is gone. The line gives the path and `(old line N)`, a line of the file at the merge base | No | Step 6 |
| `NOT CHECKED` | The gate does not know the comment syntax of the file | No | Step 6 |

A block that moved to another file has the note `(moved from <path>, old line N)`, and the gate compares it with its old text. A block in a path that you gave with `--user-facing` keeps its kind and has the note `(user-facing, not flagged)`. It is never a flag. Step 6 says how you judge it.

When the output has too many blocks to pair across files, a line ends with `NOT PAIRED ACROSS FILES, too many to compare; read their diff`, and a block that moved to another file shows as `REMOVED` in one file and `ADDED` in the other. Step 6 says what you do.

The last line gives the counts, such as `2 flagged, 6 listed, 1 removed, 1 not checked`, and ends with `, 800 not paired across files` or another count when the pairing across files did not run.

**If `python3` is missing or older than 3.9,** the gate cannot run. If you have not already done so in this session, tell the user once that the gate needs Python 3.9 or later. Then compare by hand. Read `git diff "$REVIEW_BASE"`, and give each comment that the diff adds, changes, or removes the kind from the table above. Continue with step 6. In your report, say that the gate did not run.

## Apply the verdicts

The evaluator gives each sentence a verdict, `KEEP`, `MOVE`, `CUT` or `ASK`, and marks it "base" or "added", as its prompt defines them.

- **A sentence that a review round added:** apply `KEEP`, `MOVE` and `CUT` as the evaluator gives them. Where it wrote a shorter sentence, use that sentence. For a sentence with the mark "by instruction", see **Instructions and findings**.
- **Text from before the review:** a base sentence, or text that the pull request wrote before the review, which the gate and the evaluator see as added when the gate compares with the target branch. A round does not delete or move such text on its own decision: record its verdict in the table of step 9 as a proposal, and leave the text. Apply the verdict only when a finding of the round is about that text, when an instruction asks for it, or when the text is false.
- **`ASK`, for a sentence that a review round wrote:** find the source, as the evaluator prompt defines it. If you find one, send the sentence and its source to the evaluator again, one time. A second `ASK` is final. If you have no source, or the second verdict is `ASK`, delete the sentence and write it in the table with "no source". For text from before the review, an `ASK` is a proposal, as the item above says.
- **A verdict that is wrong about the code,** such as `CUT` for a caller fact that a code line shows, `KEEP` for a false sentence, or `MOVE` to a wrong line: you can contest it one time. Send the sentence to a fresh evaluator with the code that shows that the verdict is wrong, and nothing else. The second verdict stands. If you still think that it is wrong, apply it, and quote the sentence in full in your report to the user.
- **A sentence that you know to be false is never kept,** whatever the verdict. Correct it, as the case "false comment" says.

## Judge the lines with no flag

For each line with no flag, read the block and write one line in your notes.

- **`ADDED` or `CHANGED`:** read the diff of the block from the merge base. For a block that an instruction produced, see **Instructions and findings**. For each other block, name the rule of the comment rules that the block satisfies now, and the block stays. If you cannot name one, undo the edit of the review: delete an `ADDED` block, and give a `CHANGED` block its text at the merge base. A block that corrects a false comment stays. For text from before the review, record the result as a proposal, as **Apply the verdicts** says. For a `CHANGED` block, also find each fact that the old text held and the new text does not, and treat it as a removed fact.
- **`REMOVED`:** read the old text of the block at the merge base. If no finding, no instruction, and no removal of the code that it describes caused the removal, put the block back. The item on text from before the review in **Apply the verdicts** says why. Otherwise: did the block hold a fact that the code cannot show? If not, the removal is correct. If it did, give the fact its place in this round, as the red flag about a deleted fact in the comment rules says. When an instruction told you to remove the block, the place is your reply: name the fact there, as the section "Overview" of `feature-dev-workflow:writing-code-comments` says, and do not put the block back.
- **A block with the note `(user-facing, not flagged)`:** if its kind is `GREW`, send it to the evaluator with the flags and the mark "text that users read". Otherwise make sure that each sentence of it is true and that no sentence describes how the body works.
- **`NOT CHECKED`:** read the diff of the file from the merge base. For each comment in it that the diff adds, changes, or removes, give it the kind from the table in **Read the gate**. Send each comment that got longer to the evaluator with the flags.
- **`NOT PAIRED ACROSS FILES`:** read the diff of each file that has an `ADDED` or a `REMOVED` line. Find each block that moved to another file. If it got longer, send it to the evaluator with the flags.

## Example

The code:

```
// quote_fare returns the price of the trip for the rider, in cents.
// It returns 0 when the trip is free.
function quote_fare(trip, rider)
    if not tariffs.loaded()
        fail "tariffs are not loaded"
    if rider.age < 12
        return 0
    return round(trip.distance * tariffs.rate() * rider.discount())
```

Finding 1: "The doc comment must say how the price is computed: the distance, the rate, and the discount." The case is "how the body works": how the body computes the price does not change what a caller writes. The reply declines it.

Finding 2: "The doc comment does not say that quote_fare can fail, and a caller can read a failure as a price of 0." The case is "missing caller fact". The fix adds that fact and nothing else:

```
// quote_fare returns the price of the trip for the rider, in cents.
// It returns 0 when the trip is free. It fails when the tariffs are
// not loaded, and a failure is not a price of 0.
```

The evaluator gives `KEEP` to the new sentence: its source is the line with `fail`, and the caller code is a handler for the failure.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "The reviewer is senior, so I do what the finding says" | Seniority does not change the case of a finding |

## Red flags

- You are about to make a comment longer for a reason that **Classify the finding** does not list. Go back to **Classify the finding**.
- You are about to decline a finding that is true about the code and names a caller fact. Go back to **Classify the finding**.
- You are about to push, and the gate did not run after the verdicts were applied, or it shows a flag that is not done. Go back to step 8.
- You are about to keep a sentence that a review round wrote against its verdict. Unless an instruction produced it, the one way is the contest in **Apply the verdicts**. Go back there.
