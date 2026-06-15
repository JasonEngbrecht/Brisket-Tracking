# Using Claude Code with Git & GitHub — A Beginner's Primer

A short guide to working on your projects with Claude Code and version control.

---

## The mental model (read this once)

- **Git** = a "save history" system on your computer. Each save is a **commit** — a labeled snapshot you can always return to.
- **GitHub** = a website that stores a copy of that history online (backup + sharing). Your online copy is called **origin**.
- **Repository ("repo")** = one project folder that Git is tracking. Yours is `Brisket Tracking`, linked to `github.com/JasonEngbrecht/Brisket-Tracking`.

The everyday rhythm is just three steps: **change → commit → push**.

```
edit files  →  git add .  →  git commit -m "what changed"  →  git push
                         (save a snapshot locally)         (send it to GitHub)
```

---

## How to work WITH me (Claude Code)

Think of me as a teammate who can do the Git work for you. You don't need to memorize commands — **just ask in plain English.** Examples:

- *"Commit what we've done so far with a good message."*
- *"Push my changes to GitHub."*
- *"What have I changed since the last commit?"*
- *"Undo my last commit but keep the changes."*
- *"Show me the history of this file."*

I'll run the commands, show you the result, and explain anything surprising.

### A few good habits

1. **Commit often, in small chunks.** After each working change ("added the temperature chart", "fixed the export bug"), ask me to commit. Small commits = easy to undo one thing without losing others.
2. **Push at the end of a session.** Pushing is your off-site backup. If your laptop dies, your work is safe on GitHub.
3. **Let me write the commit messages.** I'll summarize what actually changed. You can always tell me to reword.
4. **Ask before big/destructive things.** If you want to throw away changes or rewrite history, say so explicitly — I'll confirm before doing anything hard to reverse.

---

## When I'll ask vs. just do it

- **I'll just do it:** commits, pushes, checking status, showing history, creating branches — normal forward progress.
- **I'll pause and confirm first:** anything that *deletes* work, *force-pushes*, or *rewrites* history, because those are hard to undo.

You stay in control; I narrate what I'm doing.

---

## Branches (you can ignore this at first)

A **branch** is a parallel copy where you can try something risky without touching your working version (`main`). When you're comfortable, ask me: *"Make a branch for trying X."* If the experiment works, we merge it into `main`; if not, we throw the branch away and `main` is untouched. For solo projects, working directly on `main` is perfectly fine to start.

---

## Your machine's specifics (so commands "just work")

- Git and the GitHub CLI (`gh`) are **per-user installs**. They're on your PATH, but **a PowerShell window must be opened *after* they were installed** to see them.
- ➡️ **If a `git` or `gh` command says "not found," just open a fresh PowerShell window.** That fixes 90% of setup hiccups.
- You're already logged in to GitHub via `gh`, so pushing won't ask for a password.

---

## The only commands worth recognizing

You can let me run all of these, but it helps to recognize them:

| Command | Plain meaning |
|---|---|
| `git status` | What's changed but not yet saved? |
| `git add .` | Stage all changes for the next snapshot |
| `git commit -m "msg"` | Take the snapshot (save locally) |
| `git push` | Upload commits to GitHub |
| `git pull` | Download changes from GitHub (e.g. edited on another computer) |
| `git log --oneline` | List of past commits |

---

## If something looks scary

Git error messages are wordy and often harmless. **Copy the whole thing and paste it to me** — I'll tell you whether it matters and what to do. You very rarely lose work in Git; almost everything is recoverable, and I can help you get it back.

---

### TL;DR
Edit your code → ask me to **commit** → ask me to **push**. Open a fresh terminal if a command isn't found. Paste me any error. That's it.
