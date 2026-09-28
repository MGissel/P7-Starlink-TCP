# ###################################
# Group ID : 743
# Members : Cristian M. Ion, Frederik B. B. Jepesen, Ib L. M. Nielsen, Mathias M. Gissel
# Date : September 28
# Lecture: 4 Introduction to Machine Learning
# Dependencies: numpy, matplotlib, sklearn, scipy 
# Python version: 3.14.3
# Functionality: Short Description. This script uses PCA and LDA transormation 
# to reduce 784 dims to 2 dims and classifies into classes, with accuracy and error rate. 
# ###################################

#Do exercise:  from the 10-class database, choose three classes (5, 6 and 8) and then reduce dimension to 2 using LDA.  
#Since we are working on images we will normalize by dividing by 255

import numpy as np
import matplotlib.pyplot as plt
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis as LDA
from sklearn.decomposition import PCA
from scipy.stats import multivariate_normal as mvn
from scipy.stats import norm

def pca_transform(classes, dt, dim, pca = None):
    class0 = np.loadtxt(f"mnist_all/{dt}{classes[0]}.txt") / 255
    class1 = np.loadtxt(f"mnist_all/{dt}{classes[1]}.txt") / 255
    class2 = np.loadtxt(f"mnist_all/{dt}{classes[2]}.txt") / 255

    #Labels are not used, but makes it easier to compute stuff later, so ive kept them
    labels = np.concatenate([0*np.ones(len(class0), dtype=int), 1*np.ones(len(class1), dtype=int), 2*np.ones(len(class2), dtype=int)])
    data = np.concatenate([class0, class1, class2])

    if pca == None:
        pca = PCA(n_components=dim)
        pca.fit(data)

    transformed = pca.transform(data)
    return transformed, labels, pca


def lda_transform(classes, dt, dim, clf=None):
    class0 = np.loadtxt(f"mnist_all/{dt}{classes[0]}.txt") / 255
    class1 = np.loadtxt(f"mnist_all/{dt}{classes[1]}.txt") / 255
    class2 = np.loadtxt(f"mnist_all/{dt}{classes[2]}.txt") / 255

    labels = np.concatenate([0*np.ones(len(class0), dtype=int), 1*np.ones(len(class1), dtype=int), 2*np.ones(len(class2), dtype=int)])
    data = np.concatenate([class0, class1, class2])

    if clf == None:
        clf = LDA(n_components=dim)
        clf.fit(data, labels)

    transformed = clf.transform(data)
   
    return transformed, labels, clf

def classification(test_data, real_class, data, priors, len_array, width, dim): 
    length = len(test_data)

    priors = np.log(priors)
    means = np.nanmean(data, axis=0).reshape(-1, dim) #Take mean of each col instead of every item should also work with single dim

    likelihood_array = np.zeros((length, len(priors)))
    if dim > 1: #For multi dim
        for i in range(0, width, dim):
            col = i // dim 
            train_data = data[:len_array[col], i: dim+i]
            cov= np.cov(train_data.T)

            likelihood_array[:, col] = mvn.logpdf(test_data, mean=means[col], cov=cov)+priors[col]

    else: #Single dimension
        standard_devs = np.nanstd(data, axis=0)
        for col in range(0, width):
            train_data = data[:len_array[col], col]
            likelihood_array[:, col] = (norm.logpdf(test_data, loc=means[col], scale=standard_devs[col])+priors[col]).flatten()

    choice = np.argmax(likelihood_array, axis=1)
    acc = (np.count_nonzero(real_class == choice))/(length)
    print(f"Classification accuracy {acc}: Error/Misclassification rate {1-acc}")

#Remember for LDA max dim = classes-1
dim = 2 
classes = np.array([5, 6, 8])
labels = np.arange(len(classes))
data_type = np.array(["train", "test"])

#CLF is very important to reuse otherwise will be very wrong 
train_data_lda, train_labels, clf = lda_transform(classes, data_type[0], dim)
test_data_lda, test_labels, _ = lda_transform(classes, data_type[1], dim, clf)

train_data_pca, _, pca = pca_transform(classes, data_type[0], dim)
test_data_pca, _, _ = pca_transform(classes, data_type[1], dim, pca)

#Count times of every label (changed labels to 0, 1, 2 to better work with bincount) ie length of each
size_array = np.bincount(train_labels)
max_len = np.max(size_array)
width = len(classes)*dim
data_lda = np.full((max_len, width), np.nan) #Since the classes are often not same size, fill the leftover spaces with nan values, (there are mean and std functions that ignore them)
data_pca = np.full((max_len, width), np.nan)

#Dynamically allocate row/dims to data 
for i in range(0, width, dim):
    clmn = i//dim
    data_lda[:size_array[clmn], i:i+dim] = train_data_lda[train_labels == clmn]
    data_pca[:size_array[clmn], i:i+dim] = train_data_pca[train_labels == clmn]


priors = size_array / np.sum(size_array)
classification(test_data_lda, test_labels, data_lda, priors, size_array, width, dim)
classification(test_data_pca, test_labels, data_pca, priors, size_array, width, dim)

#Plotting 
if dim == 2:
    fig, ax = plt.subplots(nrows=2, ncols=2)
    clf = None 
    for index, dt in enumerate(data_type):
        train_data_lda, train_labels, clf = lda_transform(classes, dt, dim, clf)
        train_data_pca, _, pca = pca_transform(classes, dt, dim, pca)


        
        for i in range(len(classes)):   
            class_transform_lda = train_data_lda[train_labels == labels[i]]
            class_transform_pca = train_data_pca[train_labels == labels[i]]

            ax[0, index].set_title(f'{dt} LDA')
            ax[0, index].scatter(class_transform_lda[:,0], class_transform_lda[:,1], label=f"lda class {classes[i]}, type {dt}")
            ax[0, index].legend()

            ax[1, index].set_title(f'{dt} PCA')
            ax[1, index].scatter(class_transform_pca[:,0], class_transform_pca[:,1], label=f"pca class {classes[i]}, type {dt}")
            ax[1, index].legend()
    plt.tight_layout()
    plt.show()

"""
Classification accuracy 0.9444050991501416: Error/Misclassification rate 0.05559490084985841 for LDA
Classification accuracy 0.7103399433427762: Error/Misclassification rate 0.28966005665722383 for PCA
"""
