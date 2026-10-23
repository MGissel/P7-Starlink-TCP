#!/bin/bash
TRACE="${1:-20260319_mixed_losssampling_eval.trace}"

cd ~/P7-Starlink-TCP/TheaterQ
sudo insmod theaterq_lkm/sch_theaterq.ko
sudo tc qdisc add dev lo root handle 1: theaterq ingest SIMPLE
sudo tc qdisc replace dev lo root handle 1: theaterq stage CLEAR ingest SIMPLE
cd ~/P7-Starlink-TCP/Project/TheaterQ_Traces
sudo sh -c "cat $TRACE > /dev/theaterq:lo:1:0"
sudo tc qdisc change dev lo root handle 1: theaterq stage RUN cont HOLD
