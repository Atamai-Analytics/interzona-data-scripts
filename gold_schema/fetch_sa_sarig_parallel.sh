#!/usr/bin/env bash
# Parallel, resumable download of the SARIG rock-sample chemistry export (sarig_rs_chem_exp.csv, ~23.4 GB, CC BY 4.0).
# The S3 host serves ~0.13 MB/s per connection, so the file is fetched as 500 MB byte ranges, N at a time; each part resumes
# (curl -C -) and retries until it has exactly its expected size, then all parts are joined in order.
# Usage: bash fetch_sa_sarig_parallel.sh <out_dir> [parallel=16]     Re-running continues where it stopped.
set -u
URL="https://dem-sdp.s3-ap-southeast-2.amazonaws.com/sarig_rs_chem_exp.csv"
OUT="$1"; P="${2:-16}"; PART=500000000
cd "$OUT" || exit 1
SIZE=$(curl -sI -m 60 "$URL" | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}')
[ -n "$SIZE" ] || { echo "could not read file size"; exit 1; }
N=$(( (SIZE + PART - 1) / PART ))
echo "$(date +%T) size $SIZE bytes, $N parts of $PART, $P at a time"
mkdir -p _parts
fetch() {
  i=$1; a=$(( i * PART )); z=$(( a + PART - 1 )); [ $z -ge $(( SIZE - 1 )) ] && z=$(( SIZE - 1 )); want=$(( z - a + 1 ))
  f=$(printf "_parts/part_%03d" "$i")
  for try in $(seq 1 60); do
    have=$(stat -c %s "$f" 2>/dev/null || echo 0)
    [ "$have" -eq "$want" ] && { echo "$(date +%T) part $i done"; return 0; }
    [ "$have" -gt "$want" ] && { echo "part $i too big ($have > $want), restarting"; rm -f "$f"; have=0; }
    curl -s -m 7200 -r $(( a + have ))-$z "$URL" >> "$f"
    sleep 3
  done
  echo "part $i FAILED after 60 tries"; return 1
}
export -f fetch; export URL PART SIZE
seq 0 $(( N - 1 )) | xargs -P "$P" -I{} bash -c 'fetch {}'
bad=0
for i in $(seq 0 $(( N - 1 ))); do
  f=$(printf "_parts/part_%03d" "$i"); a=$(( i * PART )); z=$(( a + PART - 1 )); [ $z -ge $(( SIZE - 1 )) ] && z=$(( SIZE - 1 ))
  [ "$(stat -c %s "$f" 2>/dev/null || echo 0)" -eq $(( z - a + 1 )) ] || { echo "part $i incomplete"; bad=1; }
done
[ $bad -eq 0 ] || { echo "$(date +%T) some parts incomplete - re-run to continue"; exit 1; }
echo "$(date +%T) joining"
cat $(ls _parts/part_* | sort) > sarig_rs_chem_exp.csv.joining && mv sarig_rs_chem_exp.csv.joining sarig_rs_chem_exp.csv
[ "$(stat -c %s sarig_rs_chem_exp.csv)" -eq "$SIZE" ] && { echo "$(date +%T) DONE $SIZE bytes"; rm -rf _parts; } || { echo "joined size wrong"; exit 1; }
