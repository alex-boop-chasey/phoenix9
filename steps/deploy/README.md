Puts the merged code live with the project's deployer. It skips itself unless `[deploy] with` names a
deployer and `mode` is `on-merge` (deploys at once) or `button` (asks you first). Nothing merged means
nothing deployed. A failed health check rolls the site back and asks you to acknowledge, skip or stop.
