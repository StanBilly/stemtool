import numpy as np
import numba
import pywt
from scipy import optimize as spo
from scipy import signal as sps
import matplotlib.pyplot as plt
import matplotlib as mpl

@numba.jit(cache=True)
def cleanEELS_wavelet(data,threshold):
    wave = pywt.Wavelet('sym4')
    max_level = pywt.dwt_max_level(len(data), wave.dec_len)
    coeffs = pywt.wavedec(data, 'sym4', level=max_level)
    coeffs2 = coeffs
    threshold = 0.1
    for ii in numba.prange(1, len(coeffs)):
        coeffs2[ii] = pywt.threshold(coeffs[ii], threshold*np.amax(coeffs[ii]))
    data2 = pywt.waverec(coeffs2, 'sym4')
    return data2

@numba.jit(parallel=True)
def cleanEELS_3D(data3D,method,threshold=0):
    data_shape = np.asarray(np.shape(data3D)).astype(int)
    cleaned_3D = np.zeros(data_shape)
    if method == 'wavelet':
        if (threshold > 0):
            for ii in numba.prange(data_shape[2]):
                for jj in range(data_shape[1]):
                    cleaned_3D[:,jj,ii] = cleanEELS_wavelet(data3D[:,jj,ii],threshold)
        else:
            cleaned_3D = data3D
    if method == 'median':
        if (threshold > 0):
            for ii in numba.prange(data_shape[2]):
                for jj in range(data_shape[1]):
                    cleaned_3D[:,jj,ii] = sps.medfilt(data3D[:,jj,ii],threshold)
        else:
            cleaned_3D = data3D
    return cleaned_3D

def powerlaw_fit(xdata,ydata,xrange):
    """
    Power Law Fiiting of EELS spectral data
    
    Parameters
    ----------
    xdata:  ndarray
            energy values in electron-volts
    ydata:  ndarray
            intensity values in A.U.
    xrange: ndarray
            Starting and stopping energy values 
            in electron volts
                
    Returns
    -------
    fitted: ndarray
            Background from the region of xdata
    power:  float
            The power term
    const:  float
            Constant of multiplication
                
    Notes
    -----
    We first find the array start and stop points
    to which the power law will be fitted to. Once
    done, we take the logarithm of both the intensity
    values and the energy loss values, taking care to 
    to only take the log of non-negative intensity
    values to prevent imaginary numbers from occuring.
    We then do a linear polynomial fit in numpy, and 
    return the power law fitted data, power and the 
    multiplicative constant. Since the fitting is done 
    in log-log space, we have to take the exponential
    of the intercept to get the multiplicative constant.
                 
    :Authors:
    Jordan Hachtel <hachtelja@ornl.gov>
    
    """
    start_val = np.int((xrange[0] - np.amin(xdata))/(np.median(np.diff(xdata))))
    stop_val = np.int((xrange[1] - np.amin(xdata))/(np.median(np.diff(xdata))))
    xlog = np.log(xdata[start_val:stop_val][np.where(ydata[start_val:stop_val]>0)])
    ylog = np.log(ydata[start_val:stop_val][np.where(ydata[start_val:stop_val]>0)])
    power,const = np.polyfit(xlog,ylog,1)
    const = np.exp(const)
    fitted = const * (xdata ** power)
    return fitted,power,const

def powerlaw_plot(xdata,ydata,xrange,figtitle,showdata=True):
    font = {'family' : 'sans-serif',
            'weight' : 'bold',
            'size'   : 25}
    mpl.rc('font', **font)
    mpl.rcParams['axes.linewidth'] = 4
    fitted_data, power, const  = powerlaw_fit(xdata,ydata,xrange)
    subtracted_data = ydata - fitted_data
    yrange = const * (xrange ** power)
    zero_line = np.zeros(np.shape(xdata))
    if showdata:
        plt.figure(figsize=(32,8))
        plt.plot(xdata,ydata,'c',label='Original Data',linewidth=3)
        plt.plot(xdata,fitted_data,'m',label='Power Law Fit',linewidth=3)
        plt.plot(xdata,subtracted_data,'g',label='Remnant',linewidth=3)
        plt.plot(xdata,zero_line,'r',label='Zero Line',linewidth=3)
        plt.scatter(xrange,yrange,c='b', s=200,label='Fit Region')
        plt.legend(loc='upper right',frameon=False)
        plt.xlabel('Energy Loss (eV)',**font)
        plt.ylabel('Intensity (A.U.)',**font)
        plt.xlim(np.amin(xdata),np.amax(xdata))
        plt.ylim(np.amin(ydata)-1000,np.amax(ydata)+1000)
        plt.savefig(figtitle,dpi=400)
    return fitted_data

def region_intensity(xdata,ydata,xrange,peak_range,showdata=True):
    fitted_data, _, _ = powerlaw_fit(xdata,ydata,xrange)
    subtracted_data = ydata - fitted_data
    start_val = np.int((peak_range[0] - np.amin(xdata))/(np.median(np.diff(xdata))))
    stop_val = np.int((peak_range[1] - np.amin(xdata))/(np.median(np.diff(xdata))))
    data_floor = np.amin(subtracted_data[start_val:stop_val])
    peak_sum = np.sum(subtracted_data[start_val:stop_val] - data_floor)
    yrange = np.zeros_like(peak_range)
    yrange[0] = subtracted_data[start_val]
    yrange[1] = subtracted_data[stop_val]
    zero_line = np.zeros(np.shape(xdata))
    if showdata:
        plt.figure(figsize=(20,10))
        plt.plot(xdata,ydata,'c',label='Original Data',linewidth=3)
        plt.plot(xdata,subtracted_data,'g',label='After background subtraction',linewidth=3)
        plt.plot(xdata,zero_line,'b',label='Zero Line',linewidth=2)
        plt.scatter(peak_range,yrange,c='r', s=200,label='Sum Region')
        plt.legend(loc='upper right')
        plt.xlabel('Energy Loss (eV)')
        plt.ylabel('Intensity (A.U.)')
        plt.title('Sum from region = {}'.format(peak_sum))
        plt.xlim(np.amin(xdata),np.amax(xdata))
        plt.ylim(np.amin(ydata)-1000,np.amax(ydata)+1000)
    return peak_sum

@numba.jit(parallel=True)
def eels_3D(eels_dict,fit_range,peak_range,clean_val=0):
    fit_range = np.asarray(fit_range)
    peak_range = np.asarray(peak_range)
    no_elements = len(peak_range)
    eels_array = eels_dict['data']
    if (clean_val > 0):
        eels_clean = cleanEELS_3D(eels_array,'median',clean_val)
    else:
        eels_clean = eels_array
    xdata = (np.arange(eels_clean.shape[0]) - eels_dict['pixelOrigin'][0])*eels_dict['pixelSize'][0]
    peak_values = np.zeros((eels_clean.shape[-2],eels_clean.shape[-1],no_elements), dtype=np.float64)
    for ii in numba.prange(eels_clean.shape[-2]):
        for jj in range(eels_clean.shape[-1]):
            for qq in range(no_elements):
                eels_data = eels_clean[:,ii,jj]
                fit_points = fit_range[qq,:]
                peak_point = peak_range[qq,:]
                peak_val = region_intensity(xdata,eels_data,fit_points,peak_point,showdata=False)
                peak_values[ii,jj,qq] = peak_val
    return peak_values