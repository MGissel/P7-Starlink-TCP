name="${PWD##*/}"

sudo dmesg -k -W -l debug > test.log & #Messegaes are only logged if there are printk on KERN_DEBUG level.
DMESG_PID=$!
iperf3 -c 127.0.0.1 -t 10
sudo kill $DMESG_PID
