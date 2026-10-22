# Keeping Google Cloud costs bounded

Google Cloud has no hard "stop spending at $X" switch either. Budgets send alerts, but they don't shut anything down, and billing data lags by hours. What works is making large bills impossible or short-lived: limit what can run at once, make VMs stop when idle or after running too long, and get warned early.

The project (`kirk-souly-c11-vm`) is in an organisation account, so some of these settings belong to its administrators. Each step below says who sets it.

## 1. Limit how much can run at once (a hard limit; administrator)

Compute Engine quotas cap the vCPUs running in a region: **IAM & Admin → Quotas**, filtered to `us-central1` and the N4A CPU quota (and the overall CPUs quota). Google refuses any start that would go over them, whatever a script or a mistake asks for. If the quota is set to the size of the largest VM you plan to run (48 for one n4a-standard-48), a second VM can't be started by accident. Quotas can be lowered without approval; raising one needs a request.

## 2. Limit what the VM can do (administrator)

`deploy/gcp.sh` creates VMs that run as the service account `vm-runtime-sa`. That account's roles decide what code on the VM can do in the project. The agents never get it: their containers have no network at all. The script itself uses your own login (`gcloud auth login`). Your roles decide what you can create; ask the administrators to limit them to Compute Engine in this project, if they haven't already.

The VM gets no public IP (`--no-address`). SSH goes only through IAP, and OS Login controls who can log in and who gets sudo. There are no SSH keys or firewall rules for the script to manage.

## 3. VMs stop themselves (automatic)

`deploy/gcp.sh launch` sets this up on every VM:

- **When idle:** the VM stops itself 120 minutes after its last swarmbench run, screen, experiment or judge ends and nobody has typed in a terminal. Typing keeps it up for 30 minutes more, so the stop comes 2–2.5 hours after you leave. A forgotten `swarm view` or a tmux clock doesn't count. This is `deploy/idle-stop.sh`, installed by `deploy/bootstrap.sh`; the same script runs on AWS.
- **Busy or not:** it also stops 24 hours after each start, so a stuck run or a workload that never ends can't bill for more than a day.
- **A backstop outside the VM:** Google Cloud's own *max run duration* (`--max-run-duration 24h --instance-termination-action STOP`) stops the VM after the same 24 hours, even if the VM itself is stuck and can't run its stop script. This replaces the CloudWatch network-traffic alarm used on AWS.

Change them at launch (`--idle-minutes N`, `--max-uptime-hours H`; 0 turns one off, and `--max-uptime-hours 0` also drops Google's limit) or later on the VM in `/etc/vm-idle-stop`. For a run that needs more than a day, raise the limit before starting it. Google's limit is set on the VM itself, so it can only be changed from outside the VM (the Google Cloud console, or `gcloud compute instances update` while the VM is stopped).

**Keep-alive** (`deploy/gcp.sh keep-alive on`, or `launch --keep-alive`) turns off both of the VM's own stops, so it keeps its capacity through stockouts. It then runs, and bills, around the clock until you stop it. For a 32-core VM that's on the order of $1,000 a month. `keep-alive off` puts the stops back.

A stopped VM keeps its disk, which still bills. Delete VMs you won't use again (`deploy/gcp.sh delete`, after `deploy/gcp.sh fetch`). `deploy/gcp.sh start` brings a stopped one back.

## 4. Get warned (Budgets; administrator)

The project has a **$1,000** budget. In **Billing → Budgets & alerts**, make sure it emails you at 50% and 80% of actual spend and at 100% of forecast. A budget only alerts. Stopping or blocking resources at the limit needs extra plumbing (a Pub/Sub topic and a function), which the steps above make unnecessary for a single VM. Budget numbers lag by several hours, so they are a backstop to steps 1–3, not a brake.

This is weaker than the AWS setup in two ways. On AWS, a budget action can automatically block new launches and restarts at the limit, and the CLI user's policy caps disk size. Here, neither exists unless the administrators add them. They could add an organisation policy for machine types and disk sizes, or a budget-triggered function.

## What the worst case looks like with all of this

- **Compute:** one VM of the quota's size, running at most 24 hours from each start, and stopping 2–2.5 hours after work ends.
- **Storage:** the disks of VMs you keep.
- **Restarts:** a VM started again and again, or several VMs under different names (if the quota allows), multiplies that. That's what the budget alerts are for.

Model spend (OpenRouter, Anthropic, OpenAI) is separate and usually larger. Cap it with each run's `--max-cost`, and set a credit limit on your OpenRouter key (OpenRouter → Keys → edit → credit limit).
