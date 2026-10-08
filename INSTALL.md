# Installing Asuna into DeepSeek Harness

This page is written for an agent (or a person) installing Asuna into someone's DeepSeek Harness (DSH). Follow it in
order; every step says how to check it worked.

## What you need

- **DSH 0.2.0-rc.2** with a Web profile (`dsh --profile <name>`). The plugins pin this exact version.
- **MongoDB with vector search** that the profile can reach, and a database name for Asuna. Asuna keeps all of its
  state there, and its memory recall uses Atlas Vector Search: MongoDB Atlas, the `mongodb/mongodb-atlas-local` image,
  or MongoDB Community with its search process (mongot). A plain `mongod` runs, but memory is never indexed.
- **uv** (<https://docs.astral.sh/uv/>) or **Python 3.12+**. Asuna's worker is Python; on first start it builds its own
  environment in the profile's data folder from the package's pinned `python/requirements.lock`.
- **A persona package.** Asuna is persona-agnostic: the persona (who she is, her voice, her seeds) is a separate
  package the owner provides. None is published with the release.
- **An embedding endpoint** on the local machine or network (an OpenAI-compatible `/embeddings`), for memory recall.
- Nothing extra for the sandbox: commands run under DSH's own sandbox. On Windows the account running DSH needs
  full control of the data folder, which the default location under the DSH home already has. On Linux DSH uses
  bubblewrap where unprivileged user namespaces are allowed, else Landlock (Linux 5.13+); in a container, Landlock
  needs no extra privileges. Without a usable
  Host sandbox, running code, self-development and channel adapters are off, and Asuna says so.

## 1. Install the plugins

Take the `.tgz` assets from the GitHub Release (the core, and a channel such as QQ if wanted) and the owner's persona
package, and add them to the profile with DSH's own installer:

```bash
dsh plugin --profile <name> add <release-url>/asuna-cognition-core-<version>.tgz <release-url>/asuna-napcat-qq-<version>.tgz <path-to-persona>.tgz
```

Check: the profile's Plugins page lists **Asuna Cognition Core**, the persona, and any channel.

## 2. Give DSH a model service

In DSH's own Models settings, add the model service(s) the two brains will use. Asuna's settings pick from what DSH
offers; it never stores model endpoints or keys itself.

## 3. Configure Asuna on its settings card

Open Plugins → Asuna Cognition Core. A new profile shows `Business process: not configured` and the fields to fill:

- **Character**: the installed persona.
- **Character brain / Action brain**: model service and model (reasoning effort and output limit may stay at the
  model's defaults).
- **database**: the Mongo database name.
- **mongo_uri**: already `{"$secret":"ASUNA_MONGO_URI"}`; type the connection string into the **ASUNA_MONGO_URI**
  credential field. Credentials go to DSH's credential store; the settings only keep the reference.
- **embedding**: `{"base_url":"http://<host>:<port>/v1","model":"<embedding model>"}`.
- **Python**: leave empty to let Asuna build its environment (needs uv or Python 3.12+), or give an interpreter
  that already has the pinned dependencies.
- Optional `sandbox`: `{"backend":"auto"}` (default: DSH's sandbox) or `{"backend":"none"}`.

**Save settings**, then **Apply saved settings**. The first start may take a few minutes while the Python
environment is built; the status line shows the step.

Check: the card shows `Business process: ready · Mongo: connected`, and its last status line names the sandbox
(`Sandbox: dsh`, or `none (reason)`).

Everything the profile writes goes to its data folder, `$DSH_HOME/asuna/<profile>/` by default (the floor's
`dataRoot` setting moves it). Nothing is written into the installed packages.

## 4. Optional: the action brain's work shown inline

By default the action brain's work opens in DSH's own subagent view (the work row's "open the full process" link).
Showing it inline in the main conversation needs two patched DSH UI packages, built locally — they are not published:

1. Check out DSH at tag `dsh-v0.2.0-rc.2` (commit `639ed015397290b3745d163aafe02ffee4aa3f84`) in a dedicated folder.
2. In a checkout of this repository: `node tools/build_dsh_inline.mjs --source <that folder>`. It refuses any other
   base commit or local changes and writes two `.tgz` files to `.runtime/adr008/packages/`.
3. `dsh plugin --profile <name> add <the two .tgz files>`, then restart the profile.

Check: an action brain's work row expands to its tool calls in place. Asuna detects the patched Chat by itself;
removing the packages returns it to the subagent view without errors.

## 5. Optional: a channel

A channel package connects her to a platform: `@asuna/napcat-qq` for QQ through NapCat, `@asuna/dsh-peer` for an
agent in another DSH. Install the package first, then configure it; a configured channel without its package stops
the worker (`CHANNEL_PLUGIN_NOT_INSTALLED`).

1. `dsh plugin --profile <name> add <release-url>/asuna-napcat-qq-<version>.tgz`, then restart the profile.
2. On the settings card, add the channel to the deployment fields (`channels.<id>`, and `integration` for a channel
   with a managed adapter) and its tokens to the credential fields. **Save**, then **Apply saved settings**.

What each channel needs, field by field, is in its README: [QQ](packages/channels/napcat-qq/README.md#setting-up-qq),
[DSH peer](packages/channels/dsh-peer/README.md#configuration-owner-local). The channel API the adapters use is in
[RUNTIME_API.md](RUNTIME_API.md).

Check: the Plugins page lists the channel, the card's status line is `ready`, and a message on the platform appears
in the channel's workspace on the Web page.

## Adding or removing a package later

The same commands work at any time: `dsh plugin --profile <name> add <package.tgz>` and a restart adds a channel
(then configure it, step 5); a newer `.tgz` of an installed package upgrades it. To remove a channel, delete its
settings on the card and apply, then uninstall the package on DSH's Plugins page. A profile has exactly one persona;
give a different persona its own profile and database.
