
import numpy as np
from  scipy.stats import multivariate_normal as nvm

class trainset_class:
    """
    Just a dummy object to save data in a fancy way.

    For now just a glorified dictionary.
    """
    def __init__(self,data,label,name):

        if len(data) != len(label):
            raise "Data and label number mismatch"
        self.data = data
        self.label = label # This could just be made custom, if all the data is expected to be of the same class.
        self.name = name 

        self.__means()
    def __means(self):
        """
        To calculate the means.
        """

        self.mean = np.mean(self.data,axis=0)
        self.cov = np.cov(self.data.T) #transposed data matrix.
    def set_prior(self,sample_size = None,p = None):
        """
        n = amount of data points for all classes.
        sample_size = The complete size of the training set
        """
        # TODO check if input is correct.

        if sample_size == None and p == None:
            raise "only use sample size or individual p"

        if sample_size != None:
            self.prior = len(self.data)/sample_size

        if p != None:
            self.prior = p
    def pdf(self,test_data):
        """
        Estimantes a pdf to see probability for belonging to a specefic class.
        """

        if self.prior == None:
            self.prior("Note prior not set")

            res = nvm.pdf(test_data,mean=self.mean,cov=self.cov)
        else:
            res = nvm.pdf(test_data,mean=self.mean,cov=self.cov)*self.prior

        return res


class test_set_classificaion:

    def __init__(self,data,label,name):

        if len(data) != len(label):
            raise "Data and label number mismatch"
        self.data = data
        self.label = label # Can be different.
        self.name = name 
        self.class_guess = np.zeros(len(data)) # will be assigned numbers later.