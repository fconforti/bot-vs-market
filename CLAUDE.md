# finance

The build spec is `CLAUDE_BRIEF.md`. This file describes the machine as it actually is. **Where the two disagree, this file wins.**

## Paths and names

- The repo lives at `~/personal/finance`, not `~/framework-trader`. Everything under `~/personal/` is a personal project and everything under `~/work/` is work.
- The project is called `finance`. Use that name wherever the brief says `framework-trader`: systemd units (`finance.service`/`.timer`, `finance-research.service`/`.timer`), the state directory `~/.local/state/finance/`, and so on.
- GitHub repo: `fconforti/finance` (public, so GitHub Pages works on a free account). Pages URL: `https://fconforti.github.io/finance/`.

## GitHub access (replaces the brief's SSH deploy key)

- There is **no SSH deploy key and no `github-framework-trader` host alias**. The remote is HTTPS: `https://github.com/fconforti/finance.git`.
- Auth is a fine-grained token limited to this repo, stored in `~/.secrets/finance.env` as `GH_TOKEN`. The repo's `.envrc` (`dotenv ~/.secrets/finance.env`) loads it through direnv, and git uses it through `gh auth git-credential`. Never print, copy or commit the token.
- `gh` has no global login on this machine. It works here only because `GH_TOKEN` is set.
- The commit email is set automatically for everything under `~/personal/` (`filippo.conforti@gmail.com`). Don't set `user.email` in this repo.
- `.envrc` is hidden through `.git/info/exclude`. Leave it that way.

## Unattended runs (systemd)

- direnv does not run under systemd, so the services must load the token themselves: `EnvironmentFile=%h/.secrets/finance.env`, instead of the brief's `~/.config/finance/env`. If the services need other secrets, the owner adds them with `addsecret finance <KEY>`, which writes to the same file.
- With `GH_TOKEN` in the environment, `git push` over HTTPS works as-is. No `GIT_SSH_COMMAND` is needed.
- User services only run while the owner is logged in unless lingering is on (`loginctl enable-linger filippo`; currently off). Document this in the README next to the enable commands. As the brief says, don't enable anything.
- `claude -p` uses this machine's existing Claude Code login. No `ANTHROPIC_API_KEY` is needed unless the owner decides to add one.

## Tools already installed

- `sc` 1.1.0 (Scalable CLI) at `~/.local/bin/sc`: the official release binary, checksum and minisign signature verified. It is **not logged in yet**; the owner has to authenticate it before anything that reads the account works.
- `gitleaks` 8.30.1 (system package): use it for the pre-commit secret scan, as a local hook calling the system binary.
- `uv` (system package). Python 3.13 is installed through uv; uv downloads 3.12 by itself if the project pins it.
- Not installed: `pre-commit`. Use `uv tool run pre-commit` or `uvx pre-commit` rather than installing it system-wide.
- Installing anything new: system packages come from the official Arch repos via `sudo pacman -S --needed`. Never `pacman -Sy <pkg>`. Ask the owner before using the AUR or running downloaded install scripts. Record every install in `~/system/tools.md`.

## Missing input

- The brief says to read `TUTORIAL.md` first. It is not in this repo yet. Ask the owner for it before relying on anything it would cover.
