#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   source scripts/export_nervyx_trader_credentials.sh
#   scripts/export_nervyx_trader_credentials.sh node scripts/audit_live_trader_account.mjs
#
# The password is exported only into the current shell or child command
# environment. This script does not print or write it to disk.

default_email="${NERVYX_TRADER_EMAIL:-${ALPHAFORGE_INITIAL_TRADER_EMAIL:-wajidali1984@hotmail.com}}"

if [[ -t 0 ]]; then
  read -r -p "NERVYX trader email [${default_email}]: " input_email
  trader_email="${input_email:-$default_email}"

  read -r -s -p "NERVYX trader password: " trader_password
  printf '\n'
else
  printf 'This script needs an interactive terminal so the password can be entered without echo.\n' >&2
  exit 2
fi

if [[ -z "${trader_email}" ]]; then
  printf 'NERVYX trader email is required.\n' >&2
  exit 2
fi

if [[ -z "${trader_password}" ]]; then
  printf 'NERVYX trader password is required.\n' >&2
  exit 2
fi

export NERVYX_TRADER_EMAIL="${trader_email}"
export NERVYX_TRADER_PASSWORD="${trader_password}"

unset trader_password
unset input_email
unset default_email

if (( $# > 0 )); then
  exec "$@"
fi

printf 'NERVYX trader credentials are set for this shell session.\n'
printf 'Run: node scripts/audit_live_trader_account.mjs\n'
