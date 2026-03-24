#!/usr/bin/env bash
# Prevents Mac from sleeping while Quantum Edge is running.
# Runs caffeinate until you stop it (Ctrl+C or ./stop.sh kills it).
echo "Keeping Mac awake for Quantum Edge trading..."
echo "Press Ctrl+C to allow sleep again."
caffeinate -dims -w $$
