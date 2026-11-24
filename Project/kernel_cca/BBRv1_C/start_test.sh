name="${PWD##*/}"
ip="127.0.0.1"
sudo rmmod $name.ko -f
sudo make NAME=$name
sudo insmod $name.ko
make NAME=$name clean
sudo sysctl -w net.ipv4.tcp_allowed_congestion_control="reno cubic bbr $name"
bash ../start_theaterq.sh

dmesg -k -W -l debug > test.log &
DMESG_PID=$!
iperf3 -c $ip -t 600 -C cubic
#iperf3 -c $ip -t 600 -C $name

kill $DMESG_PID

python3 ../kernel_logger/kernel_log_interval.py $name
