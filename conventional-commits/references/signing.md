# Commit signing: diagnosis and setup

Read this when `git commit -S` fails or seems to hang. Most fixes happen on the host or in the user's configuration, not inside your session. Your job is to work out what's missing and hand the user the fix that fits their setup.

Don't generate keys, copy private keys, or change signing configuration on your own. Show the user the exact commands, and run them only if they ask you to. A failed signing attempt is safe to retry: git creates no commit and leaves the staged changes as they were.

## 1. Diagnose

First make sure signing actually failed. If git created the commit but `git log --format=%G?` or `git log --show-signature` reports it as unsigned or unverified, the problem is local *verification*, not signing. Section 3 explains this. The skill's `--commit HEAD` check reads the signature from the commit object itself, so it's the reliable test.

Find out which signing format git uses and which key it wants:

```bash
git config gpg.format        # "ssh" for SSH signing; empty or "openpgp" for GPG
git config user.signingkey   # the key git will sign with (empty = guess from the committer email)
```

### SSH signing (`gpg.format` is `ssh`)

```bash
echo "$SSH_AUTH_SOCK"        # path of the agent socket, or empty
ssh-add -L                   # public keys the agent holds
```

| `ssh-add -L` result | Meaning | git's error |
|---|---|---|
| exit 2 | No agent reachable: `SSH_AUTH_SOCK` is unset, or the socket isn't forwarded into this environment | `Couldn't get agent socket?` |
| exit 1 | Agent reachable, but it holds no keys | `Couldn't find key in agent?` |
| exit 0, signing key not listed | Agent holds other keys, not the configured one | `Couldn't find key in agent?` |

If `user.signingkey` points at a passphrase-protected private key *file*, signing needs a passphrase prompt, which can't work in a non-interactive session. The fix is to load the key into the agent (section 2).

### GPG signing (the default)

```bash
gpg --list-keys "$(git config user.signingkey)"   # the public key must be in this keyring
gpgconf --list-dirs agent-socket                  # where gpg looks for the agent
```

Typical failures:

- **`No secret key`:** the key isn't in this keyring, or the agent holding it isn't reachable. If nothing is configured at all, git tries a key matching the committer email and fails this way.
- **A pinentry error such as `Inappropriate ioctl for device`:** the key needs a passphrase and there's no terminal to ask on.
- **The command hangs:** usually a passphrase prompt or a hardware key waiting for a touch.

## 2. Preferred in sandboxes: SSH signing through a forwarded agent

This is the recommended setup when you run inside a container, VM, remote machine, or other sandbox. The private key stays on the host inside the ssh-agent. The sandbox can only ask the agent to sign, it can't read the key, and no passphrase ever passes through your session.

The user does these steps:

1. **Load the signing key into the host's agent:** `ssh-add ~/.ssh/<signing-key>`, then check with `ssh-add -L`. Optionally, use `ssh-add -c` to have the host ask for confirmation each time the key is used. This needs an askpass program on the host.
2. **Make the agent socket reachable in the sandbox, and set `SSH_AUTH_SOCK` to it there.**
   - Container: `-v "$SSH_AUTH_SOCK:/run/ssh-agent.sock" -e SSH_AUTH_SOCK=/run/ssh-agent.sock`. The same flags work in docker, podman, and nerdctl.
   - Remote machine or VM over SSH: `ssh -A <host>`, or `ForwardAgent yes` for that host only in `~/.ssh/config`.
   - Many development-environment tools forward the agent automatically, so run `echo "$SSH_AUTH_SOCK"` and `ssh-add -L` inside first.
3. **Point git at the key, inside the sandbox:**
   ```bash
   git config --global gpg.format ssh
   git config --global user.signingkey "key::ssh-ed25519 AAAA... comment"   # the key's line from ssh-add -L
   ```
   The `key::` form embeds the public key, so no key file is needed in the sandbox.
4. **Register the public key as a signing key** (not only an authentication key) with the hosting platform, or signed commits show as unverified.

Security: while the socket is forwarded, any process in the sandbox can ask the agent to sign, though none can extract the key. Limit that exposure with a dedicated signing key for sandbox work, `ssh-add -c` confirmation, and forwarding only into sandboxes the user trusts.

## 3. Verifying SSH signatures locally (`gpg.ssh.allowedSignersFile`)

Signing doesn't need this setting, but verifying does. Git has no keyring for SSH keys, so it checks SSH signatures against an *allowed signers* file that says which keys belong to whom. Without that file, git reports a correctly signed commit as unsigned:

- `%G?` prints `N`.
- `git log --show-signature` prints an error saying `gpg.ssh.allowedSignersFile needs to be configured and exist for ssh signature verification`, followed by `No signature`.

That's a verification gap, not a signing failure. Don't re-sign, amend, or change anything because of it. Hosting platforms verify separately, against the signing key registered with them.

To see signatures verified locally, the user can add their own key, and teammates' keys if they like:

```bash
mkdir -p ~/.config/git
printf '%s namespaces="git" %s\n' dana@example.com "ssh-ed25519 AAAA... comment" >> ~/.config/git/allowed_signers
git config --global gpg.ssh.allowedSignersFile ~/.config/git/allowed_signers
```

Each line is `<principal> namespaces="git" <public key>`, where the principal is usually the person's email. A team can maintain one shared file listing everyone's signing keys, so each member's machine verifies the others' commits.

With the file configured, `%G?` means:

| `%G?` | Meaning |
|---|---|
| `G` | Good signature from a listed key. `%GS` shows the principal the key is listed under. Git doesn't compare it with the committer email (`%ce`), so check both if identity matters. |
| `U` | Good signature, but the key isn't listed (`No principal matched`). |
| `N` | No signature, or verification isn't configured. |

In a sandbox the file is optional. It only affects what git displays locally, not whether commits are signed.

## 4. GPG: forward the gpg-agent

For users whose signing key is a GPG key. The host's gpg-agent offers a restricted "extra" socket designed for forwarding. It handles signing requests, and any passphrase prompt appears on the host, not in the sandbox.

The user does these steps:

1. **On the host:** run `gpgconf --list-dirs agent-extra-socket` to get the host socket path. Make sure the agent is running and the key is usable there.
2. **In the sandbox:** run `gpgconf --list-dirs agent-socket` to get the path the sandbox's gpg connects to. Make the host's extra socket appear at exactly that path.
   - Container: bind-mount it, `-v <host-extra-socket>:<sandbox-agent-socket>`.
   - Over SSH: add `RemoteForward <sandbox-agent-socket> <host-extra-socket>` for that host in the host's `~/.ssh/config`. Set `StreamLocalBindUnlink yes` in the remote's `sshd_config` so a stale socket gets replaced.
   - Make sure no gpg-agent is already running in the sandbox (`gpgconf --kill gpg-agent` there), or it will occupy the socket path.
3. **Import only the public key into the sandbox:** `gpg --export --armor <KEYID> > key.asc` on the host, then `gpg --import key.asc` in the sandbox. The secret key never leaves the host.
4. **Point git at it, inside the sandbox:** `git config --global user.signingkey <KEYID>`. Leave `gpg.format` unset or set to `openpgp`.

Verification in the sandbox then usually shows `%G?` as `U`, because the sandbox keyring doesn't mark the imported key as trusted. The signature itself is good, so there's nothing to fix. To avoid a passphrase prompt for every commit, the host agent can cache the passphrase. Raise `default-cache-ttl` in the host's `gpg-agent.conf`.

## 5. General tips

- **Unlock before the session.** Load the SSH key into the agent, or sign something once on the host so gpg-agent caches the passphrase. You can't type passphrases.
- **Hardware keys that require a touch** make every signature wait for the user. If a commit seems to hang, tell the user to touch the key.
- **Password managers and OS keychains with a built-in SSH agent** work the same way as section 2. Point `SSH_AUTH_SOCK` at their socket.
- **Never do any of these, even to get a commit through:**
  - copy a private key into the sandbox
  - put a passphrase where you can read it, for example `--pinentry-mode loopback` with a passphrase file or variable
  - generate a replacement key without the user
  - fall back to an unsigned commit
