# bin/bash

make

$SIGN tcp_bbr_low_prope.ko # For frederik's pc with secure boot.

sudo insmod tcp_bbr_low_prope.ko

sudo sysctl net.ipv4.tcp_congestion_control=bbr_low_probe


make clean