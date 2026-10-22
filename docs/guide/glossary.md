# Words used in Ingat

**English** · [Tiếng Việt](glossary.vi.md)

The words you meet in Ingat's messages and documents. Where a technical name exists, it is in parentheses.

| Word | Meaning |
|---|---|
| **instance** | One installed copy of an app on your machine, with its own name (for example `lite-test`). The name is also its Docker Compose project name. |
| **app manifest** (`ingat.toml`) | A file in the app's repository that tells Ingat how the app works: its services, its data, its tasks. It holds no values of your machine. |
| **instance file** (`instance.toml`) | Your settings for one instance: source, ports, addresses, keep rules. It stays on your machine. |
| **backup copy** (bundle) | A sealed backup of one instance's data, with a checksum for every file, kept in `INGAT_BACKUPS`. |
| **checked** (verified) | Ingat re-read every file of the backup copy, found it unchanged, and the app's own checks passed, if the app has any (without them, only the files are checked). |
| **test restore** (drill), **test-restored** (restore-tested) | Ingat restored the backup copy into a separate test copy of the app that cannot reach your live data, checked it, then removed the test copy. |
| **writers** | The parts of the app that change your data. |
| **data area** (data generation) | One complete set of an app's data. A restore fills a new one; the old one is kept. |
| **operation** | One run of a command that changes things, written down step by step so it can be continued or undone. |
| **forward point** | The step of an update after which Ingat can no longer simply undo it (usually the app's data update). |
| **on hold** (frozen) | An update stopped after it had started changing data, so the writers are kept stopped on purpose until you take the way forward. |
| **approval classes** | A: reads only. B: only adds things (backups, checks) or removes what your keep rules allow; runs unattended. C: changes something; you type the instance name. D: can lose data; you type a phrase plus a random code on a real terminal (from M2). |
| **host certification** | The record that `ingat selftest --host` passed on this exact build of your system and Docker. |
