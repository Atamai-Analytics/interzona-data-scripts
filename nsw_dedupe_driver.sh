#!/bin/bash
# runs the remaining NSW dedupe batches sequentially; stops at the first problem
cd /c/Users/dean/claude_lithosurfer/lithosurfer-work
LO=${1:-20001}; END=2377092; STEP=50000
while [ $LO -le $END ]; do
  HI=$((LO+STEP))
  R=$(./nsw_dedupe_batch.sh $LO $HI)
  echo "$(date +%H:%M:%S) $R"
  case "$R" in *ERROR*|*"no output"*) echo "STOPPING: problem in batch $LO"; exit 1;; esac
  LO=$HI
done
echo "DRIVER-FINISHED"
