from __future__ import division
import numpy as np
import math
class TimeSeries(object):

    '''
    an object that generates a time-series of Lissajous function
    npoints : points per cycle (resolution of the series)
    ncycles : how many cycles to get for the function
    train_ratio : percentage of the function to be used for training   
    '''
    def __init__(self, npoints=100, ncycles=10, train_ratio=0.8, amplitude=1, curvetype='Lissajous1', seq_len = 30, batch_size = None):
        """
        curvetype (str, optional): 'Lissajous1' or 'Lissajous2'
        """
        self.nsamples = npoints * ncycles
        self.x = np.linspace(0, ncycles * 2 * math.pi, self.nsamples)

        if curvetype not in ('Lissajous1', 'Lissajous2'):
            raise NotImplementedError()

        sin_scale = 2 if curvetype is 'Lissajous1' else 6 

        def y_x(x):
            return 4.0 / 5 * math.sin(x / sin_scale)

        def y_y(x):
            return 4.0 / 5 * math.cos(x / 2)

        self.data = np.zeros((self.nsamples, 2))
        self.data[:, 0] = np.asarray([y_x(xs)
                                      for xs in self.x]).astype(np.float32)
        self.data[:, 1] = np.asarray([y_y(xs)
                                      for xs in self.x]).astype(np.float32)

        
        # X will be (no_samples, time_steps, feature_dim)
        X = self.rolling_window(a = self.data, seq_len = seq_len)

        # Get test samples; number of test samples will be an integer multiple of batch_size
        test_samples    = (int( (1-train_ratio) * X.shape[0]) // batch_size) * batch_size   
        train_samples   = X.shape[0] - test_samples - 1

        self.train = {'X': {'data' : X[:train_samples,...], 'axes' : ('N','REC','F')},
                      'y': {'data' : self.data[seq_len:train_samples + seq_len,...], 'axes' : ('N','Fo' )}}
        

        self.test = {'X': {'data' : X[train_samples:-1,...], 'axes' : ('N','REC','F')},
                      'y': {'data' : self.data[train_samples + seq_len:,...], 'axes' : ('N','Fo' )}}
        

    def rolling_window(self, a = None, seq_len = None):
        """
        Convert a into time-lagged vectors
        a           : (time_steps, feature_dim)
        seq_len     : length of sequence used for prediction
        returns  (time_steps - seq_len + 1, seq_len, feature_dim)  array
         
        """
        assert a.shape[0] > seq_len

        shape = [a.shape[0] - seq_len + 1, seq_len, a.shape[-1]]
        strides = [a.strides[0], a.strides[0], a.strides[-1]]
        return np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides)


