import numpy as np 
import matplotlib.pyplot as plt
from pathlib import Path
import sys 

def process_data(test_name):
    data = np.loadtxt(f"{Path.home()}/P7-Starlink-TCP/Project/kernel_cca/{test_name}/test.log", delimiter=",", dtype=str, usecols=(0,2,4,6,16,18)) #for multiple (0,2,4,6,18,20)

    data[:,0] = np.strings.strip(data[:,0], "[")
    data[:,0] = np.strings.strip(data[:,0], "] ")
    return data.astype(dtype=float)


def plot_data(data_matrix, threshold, start, end, compare, relative_time = False):
    nrows = np.shape(data_matrix)[1]-3
    fig, ax = plt.subplots(nrows = nrows, ncols=1)

    time = data_matrix[:, 0]
    

    if relative_time:
        time -= time[0] 
        prediction_offset = 0
    else:
        prediction_offset = time[0]
        start += time[0]
        

    end = np.max(time)-end

    


    time_mask = (start < time) & (time < end)
    time = time[time_mask]

    rtt = data_matrix[:,1][time_mask]
    cwnd = data_matrix[:,2][time_mask]
    z_score = data_matrix[:,3][time_mask]
    
    intitial_jiffey = (data_matrix[0,5] - (30*1000))
    predictions = (((np.unique(data_matrix[:,4][time_mask])[1:]-intitial_jiffey)/1000)+prediction_offset)
    predictions = predictions[predictions < end]
 


    #CWND reduction events 
    cwnd_reduction_times = time[:-1][np.diff(cwnd) < 0]
    cwnd_reduction_events = len(cwnd_reduction_times)
    cwnd_matrix = np.zeros((cwnd_reduction_events, 2))
    cwnd_matrix[:,0] =  np.where(np.diff(data_matrix[:,2]) < 0)[0][-cwnd_reduction_events:]
    cwnd_matrix[:,1] = time[:-1][np.diff(cwnd) < 0]
   
    print(cwnd_matrix) #Printing only relevant lines

    ax[0].vlines(predictions-1, 0, np.max(z_score), colors="black")
    ax[0].vlines(predictions+1, 0, np.max(z_score), colors="black")
    ax[0].hlines(y=threshold, xmin=time[0], xmax=time[-1], colors=["r"])
    ax[0].plot(time, z_score, label=f"z_scores_k")#, marker=".", s=1)
    if compare.any():
        ax[0].plot(time, compare[time_mask], label=f"Window based")#", marker=".", s=1, alpha=0.4)    

    
    
    ax[0].scatter(cwnd_reduction_times, threshold*np.ones(len(cwnd_reduction_times)), c="black", marker="x", s=3)
    ax[0].legend() 
    
    #RTT
    ax[1].scatter(time, rtt, label=f"rtt", marker=".", s=1)
    ax[1].legend() 

    #CWND
    #ax[2].vlines(predictions-1, 0, np.max(cwnd), colors="black")
    #ax[2].vlines(predictions+1, 0, np.max(cwnd), colors="black")
    ax[2].scatter(time, cwnd, label=f"cwnd", marker=".", s=1)
    #ax[2].scatter(time[z_score >= threshold], cwnd[ z_score >= threshold], label=f"threshold", marker=".", s=5, c="r")
    #ax[2].vlines(time[:-1][np.diff(cwnd) < 0], 0, max(cwnd), colors="black")
    ax[2].legend()  

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



def main(test_name, plotting=True, threshold = 25, slice = (0, 0), compare = False, relative_time = False):
    compare_arr = np.zeros(1)
    
    data_matrix = process_data(test_name)
    if compare:
        compare_arr = compare_z(data_matrix[:,1], 400)
    

    if plotting:
        plot_data(data_matrix, threshold, slice[0], slice[1], compare_arr, relative_time=relative_time)


#test_name = sys.argv[1]
test_name = "cubic_interval"
main(test_name, compare=False, relative_time=True)

