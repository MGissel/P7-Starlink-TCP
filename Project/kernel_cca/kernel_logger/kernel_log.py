import numpy as np 
import matplotlib.pyplot as plt
from pathlib import Path
import sys 



def process_data(test_name):
    data = np.loadtxt(f"{Path.home()}/P7-Starlink-TCP/Project/kernel_cca/{test_name}/test.log", delimiter=",", dtype=str)
    data_matrix = np.zeros((np.shape(data)[0], 5))

    time = np.strings.strip(data[:,0], "[")
    data_matrix[:,0] = np.strings.strip(time, "] ").astype(dtype=float) #data_matrix[0]

    data_matrix[:,1] = data[:,2].astype(dtype=int) #RTT
    data_matrix[:,2] = data[:,6].astype(dtype=int) #CWND
    data_matrix[:,3] = data[:,8].astype(dtype=int) #Z_score
    data_matrix[:,4] = data[:,40].astype(dtype=int) #SRTT WIll be moved elsewhere at somepoint 

    return data_matrix


def save_data(test_name, data_matrix):
    print(f"{test_name} missing")
    path = f"{Path.home()}/P7-Starlink-TCP/Project/kernel_cca/{test_name}/"
    np.save(path + "test.npy", data_matrix)
    np.save(path + "test_crc.npy", data_matrix[0,0])

def load_data(test_name):
    print(f"{test_name} exists")
    path = f"{Path.home()}/P7-Starlink-TCP/Project/kernel_cca/{test_name}/"

    data_matrix = np.load(path + "test.npy")
    load_crc = np.load(path + "test_crc.npy")

    if  np.loadtxt(path + "test.log", delimiter=",", dtype=str, max_rows=1, usecols=0) != f"[{load_crc}] ":
        print(f"{test_name} changed")
        data_matrix = process_data(test_name)
        save_data(test_name, data_matrix)


    return data_matrix


def plot_data(data_matrix, threshold, start, end, compare, test_name):
    fig, ax = plt.subplots(nrows = np.shape(data_matrix)[1]-1, ncols=1)
    
    time = data_matrix[:, 0] - data_matrix[0, 0]

    end = np.max(time)-end

    time_mask = (start < time) & (time < end)
    time = time[time_mask]

    z_score = data_matrix[:,3][time_mask]
    rtt = data_matrix[:,1][time_mask]
    cwnd = data_matrix[:,2][time_mask]
    srtt = data_matrix[:,4][time_mask]

    #Z_SCORE

    ax[0].scatter(time, z_score, label=f"z_scores_k", marker=".", s=1)
    if compare.any():
        ax[0].scatter(time, compare[time_mask], label=f"Window based", marker=".", s=1, alpha=0.4)    
        
    ax[0].hlines(y=threshold, xmin=time[0], xmax=time[-1], colors=["r"])
    ax[0].legend() 
    
    #RTT
    ax[1].scatter(time, rtt, label=f"rtt", marker=".", s=1)
    ax[1].legend() 

    #SRTT
    ax[2].scatter(time, srtt, label=f"srtt", marker=".", s=1)
    ax[2].legend() 

    #CWND
    ax[3].scatter(time, cwnd, label=f"cwnd", marker=".", s=1)
    ax[3].scatter(time[z_score >= threshold], cwnd[ z_score >= threshold], label=f"threshold", marker=".", s=3, c="r")
    ax[3].legend() 

    #plt.tight_layout()
    #plt.savefig(f"{Path.home()}/P7-Starlink-TCP/Project/kernel_cca/{test_name}/test.pdf")
    plt.show()

def compare_z(rtt, window_size):
    window = np.zeros((window_size))
    rtt_length = len(rtt)
    z_score = np.zeros(rtt_length)


    for i in range(rtt_length):
        window[i % window_size] = rtt[i]
        sum = np.sum(window)

        z_score[i] = (10*window_size*rtt[i])//sum

    return z_score


def main(test_name, plotting=True, threshold = 18, slice = (60, 0), compare = False):
    compare_arr = np.zeros(1)
    
    path = f"{Path.home()}/P7-Starlink-TCP/Project/kernel_cca/{test_name}/"
    """     
    if Path(path + "test.npy").exists() and Path(path + "test_crc.npy").exists():
        data_matrix = load_data(test_name)
    else:
        data_matrix = process_data(test_name)
        save_data(test_name, data_matrix) """
    
    data_matrix = process_data(test_name)
    if compare:
        compare_arr = compare_z(data_matrix[:,1], 400)
        

    if plotting:
        plot_data(data_matrix, threshold, slice[0], slice[1], compare_arr, test_name)


#test_name = sys.argv[1]
test_name = "cubic_z_score_e"
main(test_name, compare=True)

