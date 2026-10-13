#!/system/bin/sh
# L7 fleet language agent (on-car, runs as root).
# Long-polls the fleet server and applies the desired UI language. The only two
# values it ever acts on are "ru" (ru-RU) and "zh" (zh-CN); anything else is ignored.
# Config lives in /data/local/l7agent/config:  SERVER=... TOKEN=... (one per line)
#
# It reuses the exact on-device mechanism install-ru.sh uses: enable the ru overlays
# (or leave them, Android ignores them under zh) and set the persistent system locale;
# it takes effect on the next normal reboot. The agent never reboots the car itself.

DIR=/data/local/l7agent
CONF=$DIR/config
STATE=$DIR/state           # last applied rev
LOG=$DIR/agent.log
PREFIX=uz.l7ru.overlay
UA=l7agent/1

mkdir -p $DIR
log() {
    echo "$(date +%H:%M:%S) $*" >> $LOG
    # keep the log small without a temp-file dance (toybox mv was unreliable here)
    if [ "$(wc -l < $LOG 2>/dev/null || echo 0)" -gt 500 ]; then
        tail -n 200 $LOG > $LOG.new 2>/dev/null && cat $LOG.new > $LOG && rm -f $LOG.new
    fi
}

# single instance: atomic mkdir lock. The lock records the boot id + pid; a lock from an
# earlier boot is stale (PIDs get reused after reboot), as is one whose process is gone.
# (toybox `flock <n>` treats the number as a filename, so it cannot be used here.)
LOCK=$DIR/lock.d
BOOT=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
if ! mkdir $LOCK 2>/dev/null; then
    ob=$(cat $LOCK/boot 2>/dev/null); op=$(cat $LOCK/pid 2>/dev/null)
    if [ "$ob" = "$BOOT" ] && [ -n "$op" ] && grep -q l7agent /proc/$op/cmdline 2>/dev/null; then exit 0; fi
    rm -rf $LOCK; mkdir $LOCK 2>/dev/null || exit 0
fi
echo $$ > $LOCK/pid; echo "$BOOT" > $LOCK/boot
trap 'rm -rf $LOCK' EXIT INT TERM

# service hook: if the flag file exists, keep USB adb on after boot (what the engineering
# menu's ADB switch does). Only created by hand on a car under maintenance.
[ -f $DIR/adb_on ] && setprop sys.usb.config adb

[ -f "$CONF" ] || { log "no config at $CONF"; exit 1; }
. $CONF
[ -n "$SERVER" ] && [ -n "$TOKEN" ] || { log "config missing SERVER/TOKEN"; exit 1; }

SERIAL=$(getprop ro.serialno)
MODEL=$(getprop ro.product.model)
AVER=$(getprop ro.build.version.release)

# curl is not on these units; use the toybox 'wget' + a tiny helper via /system/bin.
# Android 10 toybox has 'wget' (no headers) — so use the 'nc'-free path: try 'curl', then 'wget'.
have() { command -v "$1" >/dev/null 2>&1; }
HTTP=""
have curl && HTTP=curl
[ -z "$HTTP" ] && have wget && HTTP=wget

CA=""
[ -d /system/etc/security/cacerts ] && CA="--capath /system/etc/security/cacerts"

http_get() {   # $1 url -> body on stdout, status in $HTTP_CODE
    HTTP_CODE=$(curl -s -m 70 $CA -o $DIR/resp -w '%{http_code}' \
        -H "Authorization: Bearer $TOKEN" -H "User-Agent: $UA" "$1" 2>/dev/null)
    cat $DIR/resp 2>/dev/null
}

http_post() {  # $1 url  $2 json
    if [ "$HTTP" = curl ]; then
        curl -s -m 20 $CA -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
             -H "User-Agent: $UA" -d "$2" "$1" >/dev/null 2>&1
    fi
}

apply() {  # $1 = ru | zh
    loc=ru-RU; [ "$1" = zh ] && loc=zh-CN
    log "setting persistent locale -> $1 ($loc); takes effect on next reboot"
    if [ "$DRYRUN" = 1 ]; then
        log "DRYRUN: would set $loc (not doing it)"
        report "$1" "$REV" "dryrun"
        cur_loc="$1"
        return 0
    fi
    # Enable every installed ru overlay so the Russian UI is ready once the locale is ru.
    # (Harmless to re-enable; Android ignores ru overlays while the locale is zh.)
    if [ "$1" = ru ]; then
        for p in $(cmd overlay list 2>/dev/null | sed -n "s/^.\[.\x5d *\($PREFIX[^ ]*\)/\1/p"); do
            cmd overlay enable --user 0 "$p" >/dev/null 2>&1
        done
    fi
    # Persistent locale: survives and is read by the framework on the next boot.
    setprop persist.sys.locale $loc
    settings put system system_locales $loc
    cur=$(getprop persist.sys.locale)
    log "persist.sys.locale now $cur (no reboot; applies on next ignition/boot cycle)"
    cur_loc="$1"               # we have set the desired state; loop settles
    report "$1" "$REV" "set; pending reboot"
}

report() {  # $1 locale $2 rev $3 msg
    ov=$(cmd overlay list 2>/dev/null | grep -c "\[x\] $PREFIX")
    http_post "$SERVER/api/v1/report" \
      "{\"locale\":\"$1\",\"rev\":$2,\"agent\":\"$UA\",\"model\":\"$MODEL\",\"serial\":\"$SERIAL\",\"android\":\"$AVER\",\"overlays\":$ov${3:+,\"error\":\"$3\"}}"
}

mkdir -p $DIR
# a freshly wiped car has no persist.sys.locale and runs the build default (zh-CN)
cur_loc=$(getprop persist.sys.locale); [ -n "$cur_loc" ] || cur_loc=$(getprop ro.product.locale)
cur_loc=$(echo "$cur_loc" | cut -c1-2); [ "$cur_loc" = ru ] || cur_loc=zh
have_rev=$(cat $STATE 2>/dev/null || echo 0)
log "agent start: server=$SERVER http=$HTTP locale=$cur_loc rev=$have_rev"

while true; do
    OUT=$(http_get "$SERVER/api/v1/poll?rev=$have_rev")
    want=$(echo "$OUT" | sed -n 's/.*"locale": *"\([a-z]*\)".*/\1/p')
    REV=$(echo "$OUT" | sed -n 's/.*"rev": *\([0-9]*\).*/\1/p')
    if [ -z "$want" ] || [ -z "$REV" ]; then
        log "poll: no/invalid response (${HTTP_CODE:-?}): $(echo "$OUT" | head -c 120)"
        sleep 15; continue
    fi
    if [ "$REV" != "$have_rev" ]; then
        log "server rev $REV wants $want (have locale $cur_loc)"
        echo "$REV" > $STATE
        if [ "$want" != "$cur_loc" ]; then
            apply "$want"          # sets persistent locale, no reboot
        else
            have_rev=$REV; report "$cur_loc" "$REV"   # already correct, just ack
        fi
    else
        report "$cur_loc" "$REV"   # heartbeat on each long-poll return
    fi
    sleep 2
done
