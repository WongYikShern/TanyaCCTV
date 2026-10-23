#!/bin/sh
# Recreate the sound effects in sfx/ (all synthesised; no third-party audio).
# Usage: sh make_sfx.sh   (expects ffmpeg-path to contain the path of an ffmpeg binary)
set -e
cd "$(dirname "$0")"
FF=$(cat ffmpeg-path)
mkdir -p sfx
"$FF" -hide_banner -loglevel error -y -f lavfi -i "aevalsrc='0.9*sin(2*PI*55*t)*exp(-18*t)+0.6*sin(2*PI*48*(t-0.22))*exp(-18*(t-0.22))*gte(t,0.22)':s=48000:d=1.0" sfx/heartbeat.wav
"$FF" -hide_banner -loglevel error -y -f lavfi -i "aevalsrc='0.22*sgn(sin(2*PI*if(lt(mod(t,0.36),0.18),990,660)*t))*lt(mod(t,0.18),0.14)':s=48000:d=1.44" -af "lowpass=f=3500" sfx/alarm.wav
"$FF" -hide_banner -loglevel error -y -f lavfi -i "aevalsrc='0.2*sgn(sin(2*PI*880*t))*lt(mod(t,0.22),0.14)':s=48000:d=0.44" -af "lowpass=f=3500" sfx/warning.wav
"$FF" -hide_banner -loglevel error -y -f lavfi -i "aevalsrc='0.12*sin(2*PI*1320*t)*exp(-6*t)':s=48000:d=0.6" sfx/notice.wav
"$FF" -hide_banner -loglevel error -y -f lavfi -i "anoisesrc=d=1.2:c=pink:a=0.5" -af "highpass=f=300,lowpass=f=4000,afade=t=in:d=0.8,afade=t=out:st=0.8:d=0.4,volume=0.35" sfx/whoosh.wav
"$FF" -hide_banner -loglevel error -y -f lavfi -i "aevalsrc='0.5*sin(2*PI*55*t)*exp(-3*t)+0.3*sin(2*PI*110*t)*exp(-4*t)':s=48000:d=2.5" -af "lowpass=f=400" sfx/impact.wav
"$FF" -hide_banner -loglevel error -y -f lavfi -i "aevalsrc='(0.10*sin(2*PI*55*t)+0.07*sin(2*PI*82.41*t)+0.05*sin(2*PI*110*t)+0.03*sin(2*PI*164.81*t))*(0.75+0.25*sin(2*PI*0.08*t))':s=48000:d=330" -af "lowpass=f=600,afade=t=in:d=4" sfx/drone.wav
"$FF" -hide_banner -loglevel error -y -f lavfi -i "aevalsrc='0.15*sin(2*PI*1200*t)*exp(-40*t)':s=48000:d=0.12" sfx/key.wav
echo "sound effects written to sfx/"
