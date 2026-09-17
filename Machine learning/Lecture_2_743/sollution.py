#TODO Make the accuracy calculation into a function.
# Written By Frederik B B J

import numpy as np
import matplotlib.pyplot as plt
# The Multidimensional Gaussian distribution used to estimate.
from  scipy.stats import multivariate_normal as nvm

# Making objects

class dataset:
    """
    Just a dummy object to save data in a fancy way.

    For now just a glorified dictionary.
    """

    def __init__(self,data,label,name):

        if len(data) != len(label):
            raise "Data and label number mismatch"
        self.data = data
        self.label = label
        self.name = name 



def plot2d(data_sets,show_plot=True,save_plot = False):
    """
    plot the data from dataset object, to compare the data.
    

    # TODO make the plot 
    """

    for i in range(len(data_sets)):
        plt.scatter(data_sets[i].data[:,0],data_sets[i].data[:,1], label= data_sets[i].name)

    plt.grid()
    plt.legend()
    if show_plot == True:
        plt.show()


def classify(test_data : dataset,train_x : dataset,train_y: dataset,class_props = None):
    """
    Make classification and calculates the accuracy of it.


    Not it only support two different classes and only two dimensional data.

        """

    # Statistics used to estimate the mean and covariance for a Multidimensional Gaussian distribution

    # x statistics
    train_x_mean = np.mean(train_x.data,axis=0)
    # Covariance because multi dimensional data.
    train_x_cov = np.cov(train_x.data.T) # Transpose of data

    # y statistics
    train_y_mean = np.mean(train_y.data,axis=0)
    train_y_cov = np.cov(train_y.data.T) # Transpose of data

   
    # Priors (How common is each class?)
    if class_props == None:
        prior_x = len(train_x.data) / ( len(train_x.data)+len(train_y.data))
        prior_y = len(train_y.data) / ( len(train_x.data)+len(train_y.data))  
    else:
        prior_x = class_props[0]
        prior_y = class_props[1]

    # To save the predicted class designation of the test data.
    prediction_est = np.zeros(len(test_data.label))


    for i in range(0,len(test_data.data)):
        pass

        # Estimate the propability of the data point for the different classes' pdf.
        # This is p(x|C_i)
        p_class_1 = nvm.pdf(test_data.data[i],mean=train_x_mean,cov=train_x_cov)*prior_x
        p_class_2 = nvm.pdf(test_data.data[i],mean=train_y_mean,cov=train_y_cov)*prior_y


# Does not take edge case into consideratoin
        if p_class_1 > p_class_2:
            prediction_est[i] = 1

    # Handelig edge case, assign to largest class.
        elif p_class_1 == p_class_2:

            # use the quantity in terms of datapoints.
            if prior_x >= prior_y:
                prediction_est[i] = 1
            else:
                prediction_est[i] = 2
        else:
            prediction_est[i] = 2

    # Count the number of correct predictions
    no_correct = np.count_nonzero(prediction_est==test_data.label)

    # the percentage of correct quesses
    accuracy = no_correct/(len(test_data.data))

    print(f"accurary for exercise a) = {accuracy}")
    return accuracy


if __name__ == "__main__":


    # Loading training data and test data.
    train_x = dataset(np.loadtxt("dataset1_G_noisy_ASCII/trn_x.txt"),np.loadtxt("dataset1_G_noisy_ASCII/trn_x_class.txt"),"train_x")
    train_y = dataset(np.loadtxt("dataset1_G_noisy_ASCII/trn_y.txt"),np.loadtxt("dataset1_G_noisy_ASCII/trn_y_class.txt"),"train_y")
    test_x = dataset(np.loadtxt("dataset1_G_noisy_ASCII/tst_x.txt"),np.loadtxt("dataset1_G_noisy_ASCII/tst_x_class.txt"),"test_x")
    test_y = dataset(np.loadtxt("dataset1_G_noisy_ASCII/tst_y.txt"),np.loadtxt("dataset1_G_noisy_ASCII/tst_y_class.txt"),"test_y")
    test_y_126 = dataset(np.loadtxt("dataset1_G_noisy_ASCII/tst_y_126.txt"),np.loadtxt("dataset1_G_noisy_ASCII/tst_y_126_class.txt"),"test_y_126")
    test_xy = dataset(np.loadtxt("dataset1_G_noisy_ASCII/tst_xy.txt"),np.loadtxt("dataset1_G_noisy_ASCII/tst_xy_class.txt"),"test_xy")
    test_xy_126 = dataset(np.loadtxt("dataset1_G_noisy_ASCII/tst_xy_126.txt"),np.loadtxt("dataset1_G_noisy_ASCII/tst_xy_126_class.txt"),"test_xy_126")


    # Plot to visualise training data.
    plot2d([train_x,train_y])


    #(a) classify instances in tst_xy, and use the corresponding label file tst_xy_class to calculate the accuracy;
    sollution_a =classify(test_xy,train_x,train_y)

    #(b) classify instances in tst_xy_126 by assuming a uniform prior over the space of hypotheses, and use the corresponding label file tst_xy_126_class to calculate the accuracy;
    sollution_b= classify(test_xy_126,train_x,train_y,[0.5,0.5])

    #(c) classify instances in tst_xy_126 by assuming a prior probability of 0.9 for Class x and 0.1 for Class y, and use the corresponding label file tst_xy_126_class to calculate the accuracy; compare the results with those of (b).
    sollution_c = classify(test_xy_126,train_x,train_y,[0.9,0.1])

    # compare

    print(f" Difference between accuracy between exercise 'b' and 'c' {abs(sollution_b-sollution_c)}")
