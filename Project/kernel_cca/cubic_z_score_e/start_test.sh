name="${PWD##*/}"

sudo make NAME=$name
sudo insmod $name.ko
make NAME=$name clean
sudo /sbin/sysctl -w net.ipv4.tcp_congestion_control=$name
bash ../start_theaterq.sh

dmesg -k -W -l debug > test.log &
DMESG_PID=$!
iperf3 -c 127.0.0.1 -t 3600
kill $DMESG_PID

python3 ../kernel_logger/kernel_log.py $name
