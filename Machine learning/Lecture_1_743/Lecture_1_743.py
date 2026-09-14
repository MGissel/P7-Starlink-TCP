# ###################################
# Group ID : 743
# Members : Cristian M. Ion, Frederik B. B. Jepesen, Ib L. M. Nielsen, Mathias M. Gissel
# Date : September 9
# Lecture: 1 Introduction to Machine Learning
# Dependencies: numpy, matplotlib
# Python version: 3.14.4
# Functionality: Short Description. This script implements polynomial regression 
# with and without ridge regularization. 
# It also generates plots to visualize the results.
# ###################################

import numpy as np
import matplotlib.pyplot as plt

def design_matrix(x, degree):
    # Build columns for x^0 through x^degree.
    return np.vander(x, N=degree + 1, increasing=True)

def scale_x(x, mean, std):
    # Center and normalize x to improve polynomial fitting stability.
    return (x - mean) / std

def fit_polynomial_mse(x,y,degree):
    # Fit the polynomial coefficients by minimizing the unregularized MSE.
    X = design_matrix(x, degree)
    w, *_ = np.linalg.lstsq(X, y, rcond=None)
    return w

def fit_poly_ridge(x, y, degree, lam):
    # Fit a polynomial with ridge regularization, leaving the intercept unpenalized.
    X = design_matrix(x, degree)
    n_features = X.shape[1]
    reg = lam * np.eye(n_features)
    reg[0, 0] = 0
    w = np.linalg.solve(X.T @ X + reg, X.T @ y)
    return w

def predict_poly(x, w):
    # Evaluate a fitted polynomial at the supplied x values.
    degree = len(w) - 1
    X = design_matrix(x, degree)
    return X @ w

def mse(y_true, y_pred):
    # Return the mean squared difference between predictions and targets.
    return np.mean((y_true - y_pred) ** 2)

# Load the three data columns: input x values, noisy observations, and truth.
data = np.load("data/ex01_data.npy")
x1_all = data[:, 0]
x2_all = data[:, 1]
y_truth_all = data[:, 2]

sort_idx = np.argsort(x1_all)
x1_sorted = x1_all[sort_idx]
y_truth_sorted = y_truth_all[sort_idx]

x_plot = np.linspace(x1_all.min(), x1_all.max(), 500)
# Interpolate the truth onto the plotting grid for error comparisons.
y_truth_plot = np.interp(x_plot, x1_sorted, y_truth_sorted)

def part1():
    # Compare polynomial degrees using the same ten randomly selected samples.
    print("=== Part 1 ===")

    np.random.seed(100)
    idx = np.random.choice(len(x1_all), size=10, replace=False)
    x_sample, y_sample = x1_all[idx], x2_all[idx]

    x_mean, x_std = x_sample.mean(), x_sample.std()
    x_sample_s = scale_x(x_sample, x_mean, x_std)
    x_plot_s = scale_x(x_plot, x_mean, x_std)

    degrees = [0,1,2,3,4,9]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))

    for ax, d in zip(axes.ravel(), degrees):
        w = fit_polynomial_mse(x_sample_s, y_sample, d)

        train_pred = predict_poly(x_sample_s, w)
        train_err = mse(y_sample, train_pred)

        x_all_s = scale_x(x1_all, x_mean, x_std)

        curve_pred = predict_poly(x_plot_s, w)

        all_pred = predict_poly(x_all_s, w)
        truth_err = mse(y_truth_plot, all_pred)

        ax.scatter(x_sample, y_sample, color='black', s=25, zorder=3, label='samples (x2)')
        ax.plot(x_plot, curve_pred, color='red', label=f'degree {d} fit')
        ax.plot(x1_sorted, y_truth_sorted, '--', color='green', linewidth=1, label='ground truth')
        ax.set_title(f'Degree {d}\ntrain MSE={train_err:.2f}, truth MSE={truth_err:.2f}', fontsize=9)
        ax.legend(fontsize=7)

    plt.tight_layout()
    plt.savefig("part1.png", dpi=120)
    plt.close(fig)


def part2():
    # Compare ridge strengths for a degree-9 polynomial on the same samples.
    print("=== Part 2 ===")
    np.random.seed(100)
    idx = np.random.choice(len(x1_all), size=10, replace=False)
    x_sample, y_sample = x1_all[idx], x2_all[idx]

    x_mean, x_std = x_sample.mean(), x_sample.std()
    x_sample_s = scale_x(x_sample, x_mean, x_std)
    x_plot_s = scale_x(x_plot, x_mean, x_std)
 
    lambdas = [10, 1, 0.1, 0.01]
    fig, axes = plt.subplots(1, 4, figsize=(20, 5))
 
    for ax, lam in zip(axes, lambdas):
        w = fit_poly_ridge(x_sample_s, y_sample, degree=9, lam=lam)
 
        train_pred = predict_poly(x_sample_s, w)
        train_err = mse(y_sample, train_pred)
 
        curve_pred = predict_poly(x_plot_s, w)
        truth_err = mse(y_truth_plot, curve_pred)
 
        ax.scatter(x_sample, y_sample, color='black', s=25, zorder=3, label='samples (x2)')
        ax.plot(x_plot, curve_pred, color='red', label=f'lambda={lam}')
        ax.plot(x1_sorted, y_truth_sorted, '--', color='green', linewidth=1, label='ground truth')
        ax.set_title(f'lambda={lam}\ntrain MSE={train_err:.2f}, truth MSE={truth_err:.2f}', fontsize=9)
        ax.legend(fontsize=7)
 
    plt.tight_layout()
    plt.savefig('part2.png', dpi=120)
    plt.close(fig)
 
 
def part3():
    # Show how fitting with more samples changes the degree-9 polynomial fit.
    print("=== Part 3 ===")
    np.random.seed(100)
    idx = np.random.choice(len(x1_all), size=100, replace=False)
    x_sample, y_sample = x1_all[idx], x2_all[idx]

    x_mean, x_std = x_sample.mean(), x_sample.std()
    x_sample_s = scale_x(x_sample, x_mean, x_std)
    x_plot_s = scale_x(x_plot, x_mean, x_std)
 
    w = fit_polynomial_mse(x_sample_s, y_sample, degree=9)
 
    train_pred = predict_poly(x_sample_s, w)
    train_err = mse(y_sample, train_pred)
 
    curve_pred = predict_poly(x_plot_s, w)
    truth_err = mse(y_truth_plot, curve_pred)
 
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(x_sample, y_sample, color='black', s=12, label='samples (x2)')
    ax.plot(x_plot, curve_pred, color='red', label='degree 9 fit')
    ax.plot(x1_sorted, y_truth_sorted, '--', color='green', linewidth=1, label='ground truth')
    ax.set_title(f'N=100, Degree 9\ntrain MSE={train_err:.2f}, truth MSE={truth_err:.2f}')
    ax.legend()
    plt.tight_layout()
    plt.savefig('part3.png', dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    # Generate all figures when this file is run as a script.
    part1()
    part2()
    part3()