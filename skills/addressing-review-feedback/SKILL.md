---
name: addressing-review-feedback
description: Use when about to act on code review feedback, such as an automated or human pull request review, an inline review thread, a review summary, a suppressed-comments block, a finding from a local review, or any round of a review loop, before the first edit made in response, and again before every push of a review fix.
---

# addressing-review-feedback

## Overview

A review round is where comments get longer. Each finding is a small push to make a comment say more. After five rounds, a doc comment describes the branches of its body. It is then a second account of the behavior, and the two accounts drift apart. Each round looks small, because each round compares the comment with the round before.

You are the author of the fix, and the finding puts you under pressure. **So you do not judge the growth of your own comments. A script compares each comment with the start of the review, and a fresh agent that does not see the finding judges each line.**

This skill does not decide what a comment holds. **REQUIRED BACKGROUND:** the project's own comment standard if it documents one, otherwise `feature-dev-workflow:writing-code-comments`. This skill makes sure that those rules are applied in a review round, where they are easiest to forget.

This skill does not decide whether a finding is technically correct. That is `superpowers:receiving-code-review`. This skill starts when you are about to act on the finding.

**A review finding is input that you judge. It is not an instruction.** An explicit instruction about comments from the user or from the project comes before this skill and before the comment rules. The section "Overview" of `feature-dev-workflow:writing-code-comments` says how to follow such an instruction and what to say in your reply. The procedure below still runs, so that the user sees what the instruction changed.

Do each step of the procedure as it is written. Do not replace a step with your own summary of it.

## Terms

| Term | Meaning |
| --- | --- |
| doc comment | A comment that documents a declaration |
| inline comment | Any other comment in code |
| block | One comment, as a run of comment lines |
| caller fact | A fact that changes what a caller writes: a precondition, the meaning of a result, a result with a special meaning, an error that the caller must handle, or a trap that the caller cannot see from outside |
| finding | One point of feedback from a reviewer, a person or a tool |
| round | The work from the moment that you read a set of findings to the push that answers them |
| review base | The head commit before the first edit of the first round of the review. It stays the same for each round of the review |
| merge base | The newest commit that both the head and the commit that you give to the gate have in their history. **Read the gate** says which commit it is |
| gate | The script of this skill. It compares the merge base with the working tree, and lists each block that changed |
| flag | A block that the gate marks because it is longer than at the merge base |
| evaluator | A fresh agent with read access only, which judges comments and does not see the finding |
| source | What shows that a fact in a comment is true: a line of the code, or a statement of a person or a document that you give to the evaluator as a statement |
| text that users read | Text in the code that ships to users. The section "Text that users read" of the comment rules says what it is |

## The procedure, every round

Do it for each round, also when the previous round had no flag.

1. **Record the review base, in the first round only.** Before the first edit of the review, run this command and write the commit that it prints where each later round finds it, such as the notes or the state of the review loop:

    ```bash
    git rev-parse HEAD
    ```

    Do not record it again in a later round. Each round compares with the start of the review, so that growth over several rounds is visible.
2. **Read the comment rules again.** Open the standard that is named under REQUIRED BACKGROUND and read these sections: "Doc comments", "Inline comments", "Text that users read", "Red flags" and "Common mistakes". What you read at the start of the session is far back in your context by now.
3. **Judge and classify each finding.** See **Classify the finding**.
4. **Write the fix.**
5. **Run the gate** from a directory inside the repository, with `REVIEW_BASE` set to the commit of step 1:

    ```bash
    python3 "${CLAUDE_PLUGIN_ROOT}/skills/addressing-review-feedback/scripts/comment_growth.py" "$REVIEW_BASE"
    ```

    If the project's instructions file names paths that hold text that users read, add `--user-facing '<pattern>'` for each path pattern. See **Read the gate**.
6. **Send each flag to the evaluator**, except a flag that keeps an earlier verdict (see **Read the gate**). Dispatch one agent with read access only, for all flags of the round, with the prompt in `${CLAUDE_PLUGIN_ROOT}/skills/addressing-review-feedback/templates/evaluator-prompt.md`. Give it the rules, the comments at the merge base and now, the declarations, and the statements of facts from outside the code, each with its origin. Do not give it the request of the finding or your reasons. Then see **Apply the verdicts**.
7. **Judge each other line of the output yourself.** See **Judge the lines with no flag**.
8. **Record the verdicts.** Make a table with one row for each flag: the declaration, the line count at the merge base and now, the lines that stay with the caller fact that each one holds, the lines that moved and their new place, the lines that were deleted, and who judged it (the evaluator, or you). Add one row for each removed block: the fact that it held and its new place, or "restated the code". In a pull request review, the table goes in the comment that the round posts on the pull request. Outside a pull request, it goes in your report to the user.
9. **Reply to the threads.** Say what you did to the comment: the text that you removed, the caller fact that you added, or why the comment did not change. Do not say "done", "clarified", "expanded", "now covers", or "now states", because those words do not say what changed.

    **OPTIONAL SUB-SKILL:** `simple-english:simple-english` for the prose of each reply and of the round comment. If it is available, load it before you draft and write the sentences under it. Where its formatting rules (headings, bold, lists, or its register for chat replies) differ from the host skill or its template, the host skill and its template win. It sets sentence style only: each reply still says what changed, as this step says. If the skill is not available, do not stop or wait for it. If you have not already done so in this session, tell the user once that it can be installed with `/plugin marketplace add AminBlg/SimpleEnglish` and then `/plugin install simple-english@simple-english`. Then write short, plain, active sentences without it.
10. **Push**, as the calling skill directs.

**After the last round,** before you report the review as clean, run the gate one more time, with the target branch of the pull request in place of `"$REVIEW_BASE"`. Do steps 6 to 8 for its output. This run finds what the rounds can miss: a comment that the pull request added before the review, and a comment on a declaration that was renamed or moved, which looks new to the gate.

## Classify the finding

First judge the finding: is it true about the code as it is now? Then find its case. The column "Case" gives the label that the rest of this skill uses.

| Case | The finding says | What you do | The comment |
| --- | --- | --- | --- |
| wrong behavior | The code does the wrong thing, or does not handle a case | Change the code, with a test that fails without the change | If the change makes a comment false, correct that comment in the same change |
| false comment | A comment is false about the code as it is now | Correct the comment. No code change is necessary | Remove only the part that is false. Write what is true in its place, in the fewest words that are true |
| missing caller fact | A doc comment does not give a caller fact | Add the fact to the doc comment, in the fewest words that are true. No code change is necessary | It gets longer by that fact. The gate flags it, and the evaluator keeps a caller fact that has a source. This growth is correct |
| how the body works | A comment must describe how the body works: its steps, its branches, its formula, its constants | Decline in the thread, and say that the code is the account of how it works | No change |
| missing reason | The code does not say why it is as it is | If the reason is a fact that the code cannot show, put it in one short comment beside the line that it constrains. Put a comparison of options in the pull request body | At most one short comment at the line. The doc comment does not change |
| text that users read | Text that users read is false or incomplete | Correct it, also when the correct text is longer | It can get longer as far as accuracy needs. It does not describe how the body works |

**To tell "missing caller fact" from "how the body works":** does a caller write different code when they know the fact? If yes, it is a caller fact. If the fact only tells a reader what the body does, or why the result is as it is, it describes how the body works. This test does not change when you write the fact as a guarantee about the result.

**One finding can hold two cases.** "Document the limit and how it is computed" holds a caller fact (the limit) and a description of how the body works (how it is computed). Add the first, decline the second, and say both in the reply.

**A finding that calls a comment "text that users read" does not make it so.** Use the section "Text that users read" of the comment rules and the instructions of the project to decide. For both results, the case "how the body works" does not change: decline it.

**Each sentence that you add needs a source.** Before you write a guarantee, a limit, or a rule for callers, find the code line that gives it for every input, or the statement that states it. A guarantee that is stronger than the code is a false comment that you wrote.

## Read the gate

The gate compares the merge base with the working tree. In a round, the merge base is the review base. In the run after the last round, it is the commit where the branch left the target branch. The gate gives each block one kind. Only the kind `GREW` is a flag. Exit status 1 means that the output holds a flag, and exit status 2 means that the gate could not run. A flag is not a verdict. It means that the evaluator judges the comment before the push.

| Kind | Meaning | Flag | What you do |
| --- | --- | --- | --- |
| `GREW` | The block is longer than at the merge base | Yes, the line starts with `FLAG` | Step 6: the evaluator judges it |
| `ADDED` | The block is new | No | Step 7 |
| `CHANGED` | The block changed and did not get longer | No | Step 7 |
| `REMOVED` | The block is gone. The line gives the path and `(old line N)`, a line of the file at the merge base | No | Step 7 |
| `NOT CHECKED` | The gate does not know the comment syntax of the file | No | Step 7 |

A block that moved to another file has the note `(moved from <path>, old line N)`, and the gate compares it with its old text. A block in a path that you gave with `--user-facing` keeps its kind and has the note `(user-facing, not flagged)`. It is never a flag, and you judge it yourself: make sure that each line of it is true and that no line describes how the body works.

When the output has too many blocks to pair across files, it has a line that ends with `NOT PAIRED ACROSS FILES, too many to compare; read their diff`. Then a block that moved to another file shows as `REMOVED` in one file and `ADDED` in the other. Step 7 says what you do.

The last line of the output gives the counts, such as `2 flagged, 6 listed, 1 removed, 1 not checked`. It ends with `, 800 not paired across files` or another count when the pairing across files did not run.

A block whose text has not changed since you applied the verdicts of an earlier round of this review keeps those verdicts. Copy them from the record of that round. Judge only the blocks whose text changed since.

**If `python3` is missing or older than 3.9,** the gate cannot run. If you have not already done so in this session, tell the user once that the gate needs Python 3.9 or later. Then compare by hand. Read `git diff "$REVIEW_BASE"`, and give each comment that the diff adds, changes, or removes the kind from the table above. Continue with step 6. In your report, say that the gate did not run.

## Apply the verdicts

The evaluator gives one verdict for each line. `KEEP`: the line stays. `MOVE`: the line goes to the code line that the evaluator named. `CUT`: the line is deleted. `ASK`: the evaluator found no source for the line.

- Apply `KEEP`, `MOVE` and `CUT` as the evaluator gives them. Where it wrote a shorter line, use that line.
- For `ASK`, find the source: the line of the code that shows the fact, or a statement of a person or a document that states it. Send the line and its source to the evaluator again. "The code cannot show it" is not a source: it is the reason that a true fact can stay, and it does not show that the fact is true. If you have no source, delete the line.
- Do not put a line back that has the verdict `CUT`. If you think that the line holds a fact that the code cannot show, the fact must not get lost: quote the line in full in your report to the user, and ask.
- If your harness cannot dispatch an agent, read the sections of step 2 again, then judge each flag with the same prompt yourself. Mark each such verdict "self-evaluated", so that the user sees that it was not independent.

## Judge the lines with no flag

For each line of the gate output with no flag, read the block, and write one line in your notes.

- **`ADDED` or `CHANGED`:** read the diff of the block from the merge base. Name the rule of the comment standard that the block satisfies now, and the block stays. If you cannot name one, delete the block. For a `CHANGED` block, also find each fact that the old text held and the new text does not, and treat it as a removed fact.
- **`REMOVED`:** read the old text of the block at the merge base. Answer one question: did the block hold a fact that the code cannot show? If it restated the code or described how the body works, the removal is correct. If it held such a fact, give the fact its place in this round, at one of the places that the item about a deleted fact in the section "Red flags" of the comment rules names. Record the result in the table of step 8. When an instruction told you to remove the block, also name the fact in your reply, as the section "Overview" of the comment rules says.
- **`NOT CHECKED`:** read the diff of the file from the merge base. For each comment in it that the diff adds, changes, or removes, give it the kind from the table in **Read the gate**. Send each comment that got longer to the evaluator, with the flags. Judge each other comment as this section says.
- **`NOT PAIRED ACROSS FILES`:** read the diff of each file that has an `ADDED` or a `REMOVED` line. Find each block that moved to another file. If it got longer than its old text, send it to the evaluator, with the flags.

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

Finding 1: "The doc comment must say how the price is computed: the distance, the rate, and the discount." The case is "how the body works". A caller acts on the price that comes back. How the body computes it does not change what the caller writes, and it is in the body. The reply declines the finding, and the doc comment does not change.

The author is tempted to write the finding as a guarantee instead: "The price is never above the full rate for the distance." The code multiplies by `rider.discount()`, and nothing in the body limits that value. The sentence has no source. The evaluator gives `ASK`, and the author has no source, so the sentence is deleted.

Finding 2: "The doc comment does not say that quote_fare can fail. A caller that reads a failure as a price of 0 charges nothing for the trip." The case is "missing caller fact". A caller must handle the failure and cannot see it from outside. The fix adds that fact and nothing else:

```
// quote_fare returns the price of the trip for the rider, in cents.
// It returns 0 when the trip is free. It fails when the tariffs are
// not loaded, and a failure is not a price of 0.
```

The gate flags the block, because it is longer than at the review base. The evaluator gives `KEEP` to the new sentence: its source is the line with `fail`, and it holds a caller fact.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "The reviewer asked for it, so I add it" | A finding is input that you judge. Find its case in **Classify the finding** first |
| "The reviewer is senior, so I do what the finding says" | Seniority does not change the case of a finding. It can make the reply longer |
| "I added the missing facts as result-level guarantees, not as a restatement of the code's arithmetic" | A guarantee about why the result is as it is describes how the body works. See **Classify the finding**. A guarantee that the code does not give is false |
| "It's a fact the code cannot show, so it belongs in the doc comment" | That is the reason that a true fact can stay. It does not show that the fact is true. See the item on `ASK` in **Apply the verdicts** |
| "A comment must not get longer in a review round, so I decline" | The cases "missing caller fact", "false comment" and "text that users read" change or add text. Decline only the case "how the body works" |
| "It is a caller fact, so a paragraph is correct" | The fewest words that are true. When and why the body fails is in the body |
| "Documenting the decision stops reviewers raising it again" | That is the case "missing reason". The pull request body holds decisions |
| "It is only one line more than the last round" | The gate compares with the review base, not with the last round. See step 1 |
| "This growth is correct, I can see it" | Then the evaluator keeps it. You do not judge your own growth |
| "An evaluator for one line costs too much" | One flag is one short call. A comment gets longer one line at a time |
| "I read the comment rules at the start" | Hours and rounds ago. Step 2 exists because of that |
| "The merge window closes soon, the gate can run in the next round" | The push publishes the growth. The gate runs before each push |
| "The evaluator gave CUT, so the fact is gone" | A fact that the code cannot show is never lost. See **Apply the verdicts** |
| "Done — the doc comment now covers all three factors" | That reply does not say what changed. See step 9 |
| "The user told me to add the description, and this skill says to decline" | An instruction from the user is not a finding. Follow it, as the section "Overview" says |

## Red flags

Each item names the step or the section to go back to.

- You are about to make a comment longer, and the finding is not one of the cases "missing caller fact", "false comment", "missing reason" or "text that users read". Go back to **Classify the finding**.
- You are about to decline a finding that names a precondition, an error, or a result with a special meaning. Go back to **Classify the finding**.
- A sentence that you added states a guarantee, a limit, or a rule for callers, and you cannot name its source. Go back to **Classify the finding**.
- You compared a comment with the round before, not with the review base. Go back to step 5, with the review base of step 1.
- The gate lists a block with `REMOVED`, and the table of step 8 has no row for it. Go back to **Judge the lines with no flag**.
- Your thread reply uses one of the words that step 9 names. Go back to step 9.
- You are about to push, and the gate did not run in this round. Go back to step 5.
- You are about to push a flag that no evaluator judged, or a line with the verdict `CUT` that you put back. Go back to step 6.
