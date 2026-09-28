---
name: writing-code-comments
description: Use when about to write, edit, or delete a comment in source code, such as a doc comment on a declaration, an inline comment, or a file header, or when a diff under review adds, changes, or removes comments.
---

# writing-code-comments

## Overview

A comment is a claim that someone has to keep true for as long as the code lives. The compiler, the tests, and the running program check the code. Nothing checks the comment. **Write only the claims worth maintaining: the facts a reader needs and the code cannot show.**

This skill decides whether a comment exists and what it holds. It decides what a doc comment must say. The skill `feature-dev-workflow:testing-a-feature` writes tests from what a doc comment promises, so a promise that is missing from the doc comment is a test that is missing. This skill does not set sentence style.

**The project's own comment standard comes first.** If the project documents one (in its instructions file, a style guide, or a project skill), follow it. Where it is silent, this skill is the default.

**An explicit instruction about comments, from the user or from the project, for this task, comes before this skill too.** A review finding, from a person or from a tool, is input for you to judge, not an instruction in this sense. Follow an instruction. Keep every comment it produces true, and avoid the problems that this skill lists wherever the instruction permits. In your reply to the person who gave the instruction, state in one or two sentences where the instruction differs from this skill, so that the person can reconsider. When there is no reply, state it in the pull request body. If the instruction is unclear, ask. Do not refuse it. The table `Rationalizations` at the end answers your own guesses about what people want. It never lets you overrule a direct instruction. An instruction to remove comments does not silently cover a fact that the code cannot show: ask first, or, when you cannot ask, follow the instruction and name each such deleted fact, in full, in your reply to the person who gave the instruction, or in the pull request body when there is no reply, so the person can put it back.

**OPTIONAL SUB-SKILL:** `simple-english:simple-english` for the prose of each comment you keep. If it is available, load it before you draft and write the sentences under it. Where its formatting rules (headings, bold, lists, or its register for chat replies) differ from the host skill or its template, the host skill and its template win. It sets sentence style only: this skill and the project's comment standard still decide whether a comment exists and what it may say. If the skill is not available, do not stop or wait for it. If you have not already done so in this session, tell the user once that it can be installed with `/plugin marketplace add AminBlg/SimpleEnglish` and then `/plugin install simple-english@simple-english`. Then write short, plain, active sentences without it.

## Doc comments

A doc comment is a contract. A caller must be able to use the declaration correctly without reading its body. A wrong doc comment is worse than none, because the caller trusts it.

**Give the contract, not the algorithm.** The contract is the preconditions, the meaning of the result, and the trap that a caller cannot see from outside. When you start a sentence about how the body computes its answer, stop. The caller does not need it, and it is false the first time the body changes.

```
// BAD: the algorithm
// next_retry_delay doubles first_delay for each attempt, caps the value
// at max_delay, then adds a random jitter of up to 10 percent.
function next_retry_delay(attempt, config)

// GOOD: the contract
// next_retry_delay returns the wait before the given attempt. attempt
// starts at 1. The result can exceed max_delay by up to 10 percent.
function next_retry_delay(attempt, config)
```

A heading labeled "Contract" does not make the paragraph under it one. If it restates the branches of the body, or lists the fields the body reads without saying what the caller must supply or expect, it is still the algorithm under a different name.

**Every precondition and every error that a caller must handle is part of the contract.** So is each result with a special meaning, such as an empty value. A doc comment that does not give one of them is incomplete, and the tests have nothing to check that promise against. Add it, in the fewest words that are true.

**The decision of the caller sets the size.** A doc comment holds what someone needs to call the declaration and to use what it gives back. A fact that does not change what the caller writes is not part of the contract, however true it is and however hard it was to learn.

**Move a fact, do not delete it.** The reason that a line exists goes in one short comment beside that line. A constraint that applies at one call site goes at that call site. The comparison of options, and why this one won, goes in the pull request body. When the same fact is in the doc comment and again at the line that it constrains, keep one copy. Keep it in the doc comment when the caller must handle it. Otherwise keep it at the line, because a copy in the doc comment is far from the code that can make it false.

**When the doc comment is longer than the body, and it does not generate text that users read, name the caller decision that each paragraph serves.** Decide it for yourself; do not write it in the comment. Move the paragraphs that serve none to the code that they explain. Delete the ones that explain nothing.

**The generator test.** If a tool can make the comment from the identifier and a verb, the comment holds no information. Delete it or write the fact that the name does not give.

```
// BAD: made from the name
// tenant_name returns the tenant name.

// GOOD: a fact the name does not give
// tenant_name returns the name in lower case, as the store keys use it.
```

**What needs a doc comment.** A declaration that code outside its own module can use gets one when its contract holds a fact that its name and its signature do not show: a precondition, the meaning of a result, an error, a trap. A declaration for internal use gets one only when its behavior would surprise a reader. Where the project requires a doc comment on each public declaration, follow the project, and write a fact of the contract, not the name again.

## Inline comments

An inline comment holds what the code cannot: a constraint from outside this file, an invariant that is not visible from here, or the reason that a plainer version does not work. Write that fact first, then why it forces this code.

```
// The device drops a write that starts less than 5 ms after the
// previous one ends, and it reports success for the dropped write.
wait_milliseconds(5)
device.write(chunk)
```

If you cannot write that first fact without a paraphrase of the lines below it, there is no comment to write.

**A comment that restates the code is a second specification, and it drifts.** The next reader has two accounts of one behavior and cannot tell which is current. The review then argues about the sentence, the fix edits the sentence, and the behavior stays wrong.

**Density is a signal.** When most blocks carry a comment, the one that matters is hidden among them. If a block needs prose to be followed, a better name or a smaller function comes first. The comment is the fallback.

**A comment that holds a real constraint stays.** "Comments rot" is a reason to delete a paraphrase. It is not a reason to delete a fact that the code cannot show. When you clean up comments, sort each one by what it holds, not by how many there are.

**Never write:**

- A comment that says what the next line does.
- Context about the task or the time: "added for the import flow", "in production this would...".
- A comment that describes the change you are making. That text belongs in the commit message.
- Padding that makes a comment look thorough.

## A statement is a claim, not evidence

A doc comment, an inline comment, and a page of documentation are claims that someone made when they wrote them. A failing test or a bug report is a measurement. When the two disagree:

1. Read the code to find what it does now. Do not take the statement as the answer.
2. Decide which behavior the system must have. A documented contract is not a reason to keep a behavior that causes the reported problem.
3. Change the one that is wrong: the code, the statement, or both.

**A statement that your change made false is part of your change.** Correct it in the same change, wherever it is: on the declaration, on a caller that repeats the fact, or in the documentation. Name the correction in the pull request body. Do not defer it.

## Text that users read

Some text in the code ships to users: a description in a public schema, an error message, the reference text of a public interface. For that text, accuracy comes first. When it is false, correct it, even when the correct text is longer. A doc comment that generates reference text is still a contract. It can grow as far as accuracy needs, and it never describes how the body works.

This section comes before each rule of this skill that tells you to delete, shorten, or move text. For text that users read, do not apply such a rule: keep the text, and remove only what is false.

## Red flags

Stop when you see one of these in your own diff:

- A comment and the line under it say the same thing.
- You wrote a comment to explain a name that you could have changed.
- The comment describes the change, not the code that is there.
- You edit a comment to answer a review finding, and no code line changes in the same hunk, unless the finding shows that the comment is false about the code as it is, or names a precondition, an error, or a special result that the contract lacks.
- A doc comment got a paragraph about how the body works.
- A doc comment is longer than the body that it documents, and it does not generate text that users read.
- The same fact is in the doc comment and at the line it constrains.
- You deleted a fact that was hard to learn, and you did not move it beside its code.
- Your change altered a behavior, and a comment that states the old behavior is not in your diff.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| The comment restates the name | Delete the comment |
| The comment restates the line under it | Delete it. If the line needs prose, rename or split the code |
| The doc comment explains how the body computes the answer | Shorten it to the contract: preconditions, result, what the caller must not assume |
| The doc comment repeats a fact that is at the line it constrains | Keep one copy. If the caller must handle the fact (a precondition, an error, a special result), keep it in the doc comment and delete the copy at the line. Otherwise keep it at the line and delete the copy in the doc comment |
| A review found a case that the code gets wrong, and you added a paragraph about it | Fix the code. Add a comment only if the next reader would be caught by the same case. If the review shows that a comment that is already there is false about the code as it is now, correct that comment, and remove only the part that is false. If the review names a precondition, an error, or a special result that the contract lacks, add that fact in the fewest words that are true |
| The doc comment is longer than the body, and it does not generate text that users read | Work out, for yourself, the caller decision that each paragraph serves. Move a paragraph that serves none to the code that it explains. Delete a paragraph only when it explains nothing |
| The doc comment does not give an error or a precondition that the caller must handle | Add it, in the fewest words that are true |
| A fix ships with a comment that it just made false | Correct the statement in the same change |
| A cleanup deleted a constraint from outside the file | Put it back, in one or two lines beside the code that it constrains |
| Text that users read was shortened and is now incomplete | Correct it for accuracy. The rules that shorten a comment do not apply to it |

## Rationalizations

| Thought | Reality |
| --- | --- |
| "I guess the reviewer wants documentation, so more comments are safer" | This answers your own guess about a reviewer's taste. A reviewer has to read and check each comment. A paraphrase adds review work and no information. Give the contract. This row is about your guess only. If the user or the project told you to add comments, follow that instruction |
| "A thorough doc comment shows that I understand the code" | The doc comment is for the caller. What you understood goes in the pull request body |
| "The doc update is out of scope, the task was the code fix" | The comment became false when your code changed. The correction is the same task |
| "I will note the doc update as a follow-up" | A follow-up leaves a false statement in the default branch. File follow-ups for work you did not do, not for damage you did |
| "The doc comment states the contract, so the fix must keep it" | A contract is a decision, and a decision can change. If the report shows that it is the wrong one, change it and correct the prose |
| "Comments rot, so I delete when in doubt" | A paraphrase rots. A fact that the code cannot show is the one comment that the reader needs |
| "It is a test or a helper, the rules are looser" | Comments in tests and helpers follow the same rules |
| "I explain what was added and why, so the reader doesn't have to reverse-engineer it" | The reader of the declaration is its caller. State what changed and why in the pull request body, not on the declaration |
| "I spell out the formula so the reader does not have to reverse-engineer it" | The formula is the algorithm. State the result the caller gets, including that it can exceed a limit, not how the body computes it |
| "No behavior changed, so a comments-only change is safe to land without more scrutiny" | A change of comments only gets the same check as any other change. In a doc comment, remove each description of how the body works and keep the contract. Keep an inline comment that holds a fact that the code cannot show |
| "The user told me to comment every block, but this skill says that is wrong, so I will not do it" | An instruction from the user or the project is not a rationalization. Follow it, keep what you write true, and say, in your reply to the person who gave the instruction, or in the pull request body when there is no reply, where it differs from this skill's default |
