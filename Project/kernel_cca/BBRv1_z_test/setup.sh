# bin/bash

make

$SIGN BBRv1_z_test.ko # For frederik's pc with secure boot.

sudo insmod BBRv1_z_test.ko

sudo sysctl net.ipv4.tcp_congestion_control=BBRv1_z_test


make clean