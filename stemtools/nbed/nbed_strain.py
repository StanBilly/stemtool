import numpy as np
import numba
import warnings
from scipy import ndimage as scnd
from scipy import optimize as sio
from scipy import signal as scisig
import matplotlib.colors as mplc
import matplotlib.pyplot as plt
from ..util import image_utils as iu
from ..proc import sobel_canny as sc
from ..util import gauss_utils as gt
import warnings

def angle_fun(angle,
              image_orig,
              axis=0,):
    """
    Rotation Sum Finder
    
    Parameters
    ----------
    angle:      float 
                Angle to rotate 
    image_orig: (2,2) shape ndarray
                Input Image
    axis:       int
                Axis along which to perform sum
                     
    Returns
    -------
    rotmin: float
            Sum of the rotated image multiplied by -1 along 
            the axis specified
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    rotated_image = scnd.rotate(image_orig,angle,order=5,reshape=False)
    rotsum = (-1)*(np.sum(rotated_image,1))
    rotmin = np.amin(rotsum)
    return rotmin

def rotation_finder(image_orig,
                    axis=0):
    """
    Angle Finder
    
    Parameters
    ----------
    image_orig: (2,2) shape ndarray
                Input Image
    axis:       int
                Axis along which to perform sum
                     
    Returns
    -------
    min_x: float
           Angle by which if the image is rotated
           by, the sum of the image along the axis
           specified is maximum
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    x0 = 90
    x = sio.minimize(angle_fun,x0,args=(image_orig))
    min_x = x.x
    return min_x

def rotate_and_center_ROI(data4D_ROI,
                          rotangle,
                          xcenter,
                          ycenter):
    """
    Rotation Corrector
    
    Parameters
    ----------
    data4D_ROI: ndarray 
                Region of interest of the 4D-STEM dataset in
                the form of ROI pixels (scanning), CBED_Y, CBED_x
    rotangle:   float
                angle in counter-clockwise direction to 
                rotate individual CBED patterns
    xcenter:    float
                X pixel co-ordinate of center of mean pattern
    ycenter:    float
                Y pixel co-ordinate of center of mean pattern
                     
    Returns
    -------
    corrected_ROI: ndarray
                   Each CBED pattern from the region of interest
                   first centered and then rotated along the center
     
    
    Notes
    -----
    We start by centering each 4D-STEM CBED pattern 
    and then rotating the patterns with respect to the
    pattern center
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    data_size = np.asarray(np.shape(data4D_ROI))
    corrected_ROI = np.zeros_like(data4D_ROI)
    for ii in range(data4D_ROI.shape[0]):
        cbed_pattern = data4D_ROI[ii,:,:]
        moved_cbed = np.abs(iu.move_by_phase(cbed_pattern,(-xcenter + (0.5 * data_size[-1])),(-ycenter + (0.5 * data_size[-2]))))
        rotated_cbed = scnd.rotate(moved_cbed,rotangle,order=5,reshape=False)
        corrected_ROI[ii,:,:] = rotated_cbed
    return corrected_ROI

def data4Dto2D(data4D):
    """
    Convert 4D data to 2D data
    
    Parameters
    ----------
    data4D: ndarray of shape (4,4)
            the first two dimensions are Fourier
            space, while the next two dimensions
            are real space
                     
    Returns
    -------
    data2D: ndarray of shape (2,2)
            Raveled 2D data where the
            first two dimensions are positions
            while the next two dimensions are spectra
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    data2D = np.transpose(data4D,(2,3,0,1))
    data_shape = data2D.shape
    data2D.shape = (data_shape[0]*data_shape[1],data_shape[2]*data_shape[3])
    return data2D

@numba.jit
def resizer(data,
            N):
    """
    Downsample 1D array
    
    Parameters
    ----------
    data: ndarray
    N:    int
          New size of array
                     
    Returns
    -------
    res: ndarray of shape N
         Data resampled
    
    Notes
    -----
    The data is resampled. Since this is a Numba
    function, compile it once (you will get errors)
    by calling %timeit
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    warnings.filterwarnings('ignore')
    M = data.size
    data = (data).astype(np.float64)
    res=np.zeros(int(N),dtype=np.float64)
    carry=0
    m=0
    for n in range(int(N)):
        data_sum = carry
        while m*N - n*M < M :
            data_sum += data[m]
            m += 1
        carry = (m-(n+1)*M/N)*data[m-1]
        data_sum -= carry
        res[n] = data_sum*N/M
    return res

@numba.jit
def resizer2D(data,
              sampling):
    """
    Downsample 2D array
    
    Parameters
    ----------
    data:     ndarray
              (2,2) shape
    sampling: tuple
              Downsampling factor in each axisa
                     
    Returns
    -------
    resampled: ndarray
              Downsampled by the sampling factor
              in each axis
    
    Notes
    -----
    The data is a 2D wrapper over the resizer function
    
    See Also
    --------
    resizer
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    warnings.filterwarnings('ignore')
    sampling = np.asarray(sampling)
    data_shape = np.asarray(np.shape(data))
    sampled_shape = (np.round(data_shape/sampling)).astype(int)
    resampled_x = np.zeros((data_shape[0],sampled_shape[1]),dtype=np.float64)
    resampled = np.zeros(sampled_shape,dtype=np.float64)
    for yy in range(int(data_shape[0])):
        resampled_x[yy,:] = resizer(data[yy,:],sampled_shape[1])
    for xx in range(int(sampled_shape[1])):
        resampled[:,xx] = resizer(resampled_x[:,xx],sampled_shape[0])
    return resampled

@numba.jit
def bin4D(data4D,
          bin_factor):
    """
    Bin 4D data in spectral dimensions
    
    Parameters
    ----------
    data4D:     ndarray of shape (4,4)
                the first two dimensions are Fourier
                space, while the next two dimensions
                are real space
    bin_factor: int
                Value by which to bin data
                     
    Returns
    -------
    binned_data: ndarray of shape (4,4)
                 Data binned in the spectral dimensions
    
    Notes
    -----
    The data is binned in the last two spectral dimensions
    using resizer2D function.
    
    See Also
    --------
    resizer
    resizer2D
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    warnings.filterwarnings('ignore')
    mean_data = np.mean(data4D,axis=(-1,-2),dtype=np.float64)
    mean_binned = resizer2D(mean_data,(bin_factor,bin_factor))
    binned_data = np.zeros((mean_binned.shape[0],mean_binned.shape[1],data4D.shape[2],data4D.shape[3]),dtype=data4D.dtype)
    for ii in range(data4D.shape[2]):
        for jj in range(data4D.shape[3]):
            binned_data[:,:,ii,jj] = resizer2D(data4D[:,:,ii,jj],(bin_factor,bin_factor))
    return binned_data

def test_aperture(pattern,
                  center,
                  radius,
                  showfig=True):
    """
    Test an aperture position for Virtual DF image
    
    Parameters
    ----------
    pattern: ndarray of shape (2,2)
             Diffraction pattern, preferably the
             mean diffraction pattern for testing out
             the aperture location
    center:  ndarray of shape (1,2)
             Center of the circular aperture
    radius:  float
             Radius of the circular aperture
    showfig: bool
             If showfig is True, then the image is
             displayed with the aperture overlaid
                     
    Returns
    -------
    aperture: ndarray of shape (2,2)
              A matrix of the same size of the input image
              with zeros everywhere and ones where the aperture
              is supposed to be
    
    Notes
    -----
    Use the showfig option to visually test out the aperture 
    location with varying parameters
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    center = np.asarray(center)
    yy,xx = np.mgrid[0:pattern.shape[0],0:pattern.shape[1]]
    yy = yy - center[1]
    xx = xx - center[0]
    rr = ((yy ** 2) + (xx ** 2)) ** 0.5
    aperture = np.asarray(rr<=radius, dtype=np.double)
    if showfig:
        plt.figure(figsize=(15,15))
        plt.imshow(iu.image_normalizer(pattern)+aperture,cmap='Spectral')
        plt.scatter(center[0],center[1],c='w', s=25)
    return aperture

def aperture_image(data4D,
                   center,
                   radius):
    """
    Generate Virtual DF image for a given aperture
    
    Parameters
    ----------
    data4D: ndarray of shape (4,4)
            the first two dimensions are Fourier
            space, while the next two dimensions
            are real space
    center: ndarray of shape (1,2)
            Center of the circular aperture
    radius: float
            Radius of the circular aperture
    
    Returns
    -------
    df_image: ndarray of shape (2,2)
              Generated virtual dark field image
              from the aperture and 4D data
    
    Notes
    -----
    We generate the aperture first, and then make copies
    of the aperture to generate a 4D dataset of the same 
    size as the 4D data. Then we do an element wise 
    multiplication of this aperture 4D data with the 4D data
    and then sum it along the two Fourier directions.
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    center = np.array(center)
    yy,xx = np.mgrid[0:data4D.shape[0],0:data4D.shape[1]]
    yy = yy - center[1]
    xx = xx - center[0]
    rr = ((yy ** 2) + (xx ** 2)) ** 0.5
    aperture = np.asarray(rr<=radius, dtype=data4D.dtype)
    apt_copy = np.empty((data4D.shape[2],data4D.shape[3]) + aperture.shape,dtype=data4D.dtype)
    apt_copy[:] = aperture
    apt_copy = np.transpose(apt_copy,(2,3,0,1))
    apt_mult = apt_copy * data4D
    df_image = np.sum(np.sum(apt_mult,axis=0),axis=0)
    return df_image

def ROI_from_image(image,
                   med_val,
                   style='over',
                   showfig=True):
    if style == 'over':
        ROI = np.asarray(image > (med_val*np.median(image)),dtype=np.double)
    else:
        ROI = np.asarray(image < (med_val*np.median(image)),dtype=np.double)
    if showfig:
        plt.figure(figsize=(15, 15))
        plt.imshow(ROI+iu.image_normalizer(image),cmap='viridis')
        plt.title('ROI overlaid')
    ROI = ROI.astype(bool)
    return ROI

@numba.jit
def colored_mcr(conc_data,
                data_shape):
    no_spectra = np.shape(conc_data)[1]
    color_hues = np.arange(no_spectra,dtype=np.float64)/no_spectra
    norm_conc = (conc_data - np.amin(conc_data)) / (np.amax(conc_data) - np.amin(conc_data))
    saturation_matrix = np.ones(data_shape,dtype=np.float64)
    hsv_calc = np.zeros((data_shape[0],data_shape[1],3),dtype=np.float64)
    rgb_calc = np.zeros((data_shape[0],data_shape[1],3),dtype=np.float64)
    hsv_calc[:,:,1] = saturation_matrix
    for ii in range(no_spectra):
        conc_image = (np.reshape(norm_conc[:,ii],data_shape)).astype(np.float64)
        hsv_calc[:,:,0] = saturation_matrix * color_hues[ii]
        hsv_calc[:,:,2] = conc_image
        rgb_calc = rgb_calc + mplc.hsv_to_rgb(hsv_calc)
    rgb_image = rgb_calc/np.amax(rgb_calc)
    return rgb_image

@numba.jit
def fit_nbed_disks(corr_image,
                   disk_size,
                   positions,
                   diff_spots):
    warnings.filterwarnings('ignore')
    positions = np.asarray(positions,dtype=np.float64)
    diff_spots = np.asarray(diff_spots,dtype=np.float64)
    fitted_disk_list = np.zeros_like(positions)
    disk_locations = np.zeros_like(positions)
    for ii in range(int(np.shape(positions)[0])):
        posx = positions[ii,0]
        posy = positions[ii,1]
        par = gt.fit_gaussian2D_mask(corr_image,posx,posy,disk_size)
        fitted_disk_list[ii,0] = par[0]
        fitted_disk_list[ii,1] = par[1]
    disk_locations = np.copy(fitted_disk_list)
    disk_locations[:,1] = 0 - disk_locations[:,1]
    center = disk_locations[np.logical_and((diff_spots[:,0] == 0),(diff_spots[:,1] == 0)),:]
    cx = center[0,0]
    cy = center[0,1]
    disk_locations[:,0:2] = disk_locations[:,0:2] - np.asarray((cx,cy),dtype=np.float64)
    lcbed,_,_,_ = np.linalg.lstsq(diff_spots,disk_locations,rcond=None)
    cy = (-1)*cy
    return fitted_disk_list,np.asarray((cx,cy),dtype=np.float64),lcbed

@numba.jit
def strain_in_ROI(data4D_ROI,
                  center_disk,
                  disk_list,
                  pos_list,
                  reference_axes=0,
                  med_factor=10):
    warnings.filterwarnings('ignore')
    # Calculate needed values
    no_of_disks = data4D_ROI.shape[-1]
    disk_size = (np.sum(center_disk)/np.pi) ** 0.5
    i_matrix = (np.eye(2)).astype(np.float64)
    sobel_center_disk,_ = sc.sobel(center_disk)
    # Initialize matrices
    e_xx_ROI = np.zeros(no_of_disks,dtype=np.float64)
    e_xy_ROI = np.zeros(no_of_disks,dtype=np.float64)
    e_th_ROI = np.zeros(no_of_disks,dtype=np.float64)
    e_yy_ROI = np.zeros(no_of_disks,dtype=np.float64)
    #Calculate for mean CBED if no reference
    #axes present
    if np.size(reference_axes) < 2:
        mean_cbed = np.mean(data4D_ROI,axis=-1)
        sobel_lm_cbed,_ = sc.sobel(iu.image_logarizer(mean_cbed))
        sobel_lm_cbed[sobel_lm_cbed > med_factor*np.median(sobel_lm_cbed)] = np.median(sobel_lm_cbed)
        lsc_mean = iu.cross_corr(sobel_lm_cbed,sobel_center_disk,hybridizer=0.1)
        _,_,mean_axes = fit_nbed_disks(lsc_mean,disk_size,disk_list,pos_list)
        inverse_axes = np.linalg.inv(mean_axes)
    else:
        inverse_axes = np.linalg.inv(reference_axes)
    for ii in range(int(no_of_disks)):
        pattern = data4D_ROI[:,:,ii]
        sobel_log_pattern,_ = sc.sobel(iu.image_logarizer(pattern))
        sobel_log_pattern[sobel_log_pattern > med_factor*np.median(sobel_log_pattern)] = np.median(sobel_log_pattern)
        lsc_pattern = iu.cross_corr(sobel_log_pattern,sobel_center_disk,hybridizer=0.1)
        _,_,pattern_axes = fit_nbed_disks(lsc_pattern,disk_size,disk_list,pos_list)
        t_pattern = np.matmul(pattern_axes,inverse_axes)
        s_pattern = t_pattern - i_matrix
        e_xx_ROI[ii] = -s_pattern[0,0]
        e_xy_ROI[ii] = -(s_pattern[0,1] + s_pattern[1,0])
        e_th_ROI[ii] = s_pattern[0,1] - s_pattern[1,0]
        e_yy_ROI[ii] = -s_pattern[1,1]
    return e_xx_ROI,e_xy_ROI,e_th_ROI,e_yy_ROI

@numba.jit
def strain_oldstyle(data4D_ROI,
                    center_disk,
                    disk_list,
                    pos_list,
                    reference_axes=0):
    warnings.filterwarnings('ignore')
    # Calculate needed values
    no_of_disks = data4D_ROI.shape[-1]
    disk_size = (np.sum(center_disk)/np.pi) ** 0.5
    i_matrix = (np.eye(2)).astype(np.float64)
    # Initialize matrices
    e_xx_ROI = np.zeros(no_of_disks,dtype=np.float64)
    e_xy_ROI = np.zeros(no_of_disks,dtype=np.float64)
    e_th_ROI = np.zeros(no_of_disks,dtype=np.float64)
    e_yy_ROI = np.zeros(no_of_disks,dtype=np.float64)
    #Calculate for mean CBED if no reference
    #axes present
    if np.size(reference_axes) < 2:
        mean_cbed = np.mean(data4D_ROI,axis=-1)
        cc_mean = iu.cross_corr(mean_cbed,center_disk,hybridizer=0.1)
        _,_,mean_axes = fit_nbed_disks(cc_mean,disk_size,disk_list,pos_list)
        inverse_axes = np.linalg.inv(mean_axes)
    else:
        inverse_axes = np.linalg.inv(reference_axes)
    for ii in range(int(no_of_disks)):
        pattern = data4D_ROI[:,:,ii]
        cc_pattern = iu.cross_corr(pattern,center_disk,hybridizer=0.1)
        _,_,pattern_axes = fit_nbed_disks(cc_pattern,disk_size,disk_list,pos_list)
        t_pattern = np.matmul(pattern_axes,inverse_axes)
        s_pattern = t_pattern - i_matrix
        e_xx_ROI[ii] = -s_pattern[0,0]
        e_xy_ROI[ii] = -(s_pattern[0,1] + s_pattern[1,0])
        e_th_ROI[ii] = s_pattern[0,1] - s_pattern[1,0]
        e_yy_ROI[ii] = -s_pattern[1,1]
    return e_xx_ROI,e_xy_ROI,e_th_ROI,e_yy_ROI

def ROI_strain_map(strain_ROI,
                   ROI):
    """
    Convert the strain in the ROI array to a strain map
                 
    :Authors:
    Debangshu Mukherjee <mukherjeed@ornl.gov>
    """
    strain_map = np.zeros_like(ROI,dtype=np.float64)
    strain_map[ROI] = (strain_ROI).astype(np.float64)
    return strain_map

def log_sobel(data4D):
    data_lsb = np.zeros_like(data4D,dtype=np.float64)
    for jj in range(data4D.shape[3]):
        for ii in range(data4D.shape[2]):
            data_lsb[:,:,ii,jj],_ = sc.sobel(iu.image_logarizer(data4D[:,:,ii,jj]))
    return data_lsb