#%% md
# this script can train a network on the pcam dataset.
Imports
#%% 

import os
import tensorflow as tf
import numpy as np
from tensorflow.keras.utils import HDF5Matrix
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, Activation, Flatten, Conv2D, MaxPooling2D
from tensorflow.keras.layers import GlobalAveragePooling2D
import argparse

#%% dch

if os.getcwd().endswith('code'):
    os.chdir('..')
print(os.getcwd())

#%% md
build arparser
#%%
parser = argparse.ArgumentParser()

# define the training
parser.add_argument('-lr', '--learning-rate', type=float, help='', default = 0.1)
parser.add_argument('-b','--batch-size', type=int, help='', default = 64)
parser.add_argument('--num-of-epochs', type=int, help='', default = 100)

# define the model structure
parser.add_argument('--activation-function', type=str, help='', default = 'relu')
parser.add_argument('--use-same-padding', action='store_true')
parser.add_argument('--kernel-width', type=int, help='', default = 3)
parser.add_argument('--average-kernels', type=int, help='', default = 32)
parser.add_argument('--num-of-conv-layers', type=int, help='', default = 5)
parser.add_argument('--kernel-increasing-factor', type=float, help='', default = 1.2)
parser.add_argument('--maxpool-after-n-layer', type=int, help='', default = 3)
parser.add_argument('--dropout-factor-after-conv', type=float, help='', default = 0.1)
parser.add_argument('--dropout-factor-after-maxp', type=float, help='', default = 0.25)

# define the input
parser.add_argument('--flip-input', action='store_true')
parser.add_argument('--normalize-input', action='store_true')
parser.add_argument('--use-cropping', action='store_true')

#%%
args = parser.parse_args()

validation_steps=20
steps_per_epoch=100

#%% dvc-cc-hide
class Args:
    def __init__(self):
        print()
        
args = Args()

args.learning_rate = 0.1
args.batch_size = 64
args.num_of_epochs = 2

args.activation_function = 'relu' ##########
args.use_same_padding = True ##############
args.kernel_width = 3 ######################
args.average_kernels = 64 ###########
args.kernel_increasing_factor = 1.5 ###########
args.num_of_conv_layers = 5 #############################
args.dropout_factor_after_conv = 0.1 ##########
args.dropout_factor_after_maxp = 0.25 #########

args.maxpool_after_n_layer = 2

args.flip_input = True
args.normalize_input = True
args.use_cropping = True

validation_steps=2
steps_per_epoch=10

#%% md
Load the dataset:
#%%
x_train = HDF5Matrix('data/camelyonpatch_level_2_split_train_x.h5', 'x')
y_train = HDF5Matrix('data/camelyonpatch_level_2_split_train_y.h5', 'y')
x_valid = HDF5Matrix('data/camelyonpatch_level_2_split_valid_x.h5', 'x')
y_valid = HDF5Matrix('data/camelyonpatch_level_2_split_valid_y.h5', 'y')

#%% md
define the model

#%%
if args.use_same_padding:
    padding = 'same'
else:
    padding = 'valid'

kernel2d = (args.kernel_width, args.kernel_width)

#%%
model = Sequential()
for i in range(args.num_of_conv_layers):
    kernels = args.average_kernels * (args.kernel_increasing_factor ** (i-(args.num_of_conv_layers/2.)))
    kernels = int(kernels+0.5)
    
    if i == 0:
        input_shape = list(x_train.shape[1:])
        if args.use_cropping:
            input_shape[0] -= 10
            input_shape[1] -= 10 
        
        model.add(Conv2D(kernels, kernel2d, padding=padding,
                 input_shape=input_shape))
    else:
        model.add(Conv2D(kernels, kernel2d, padding=padding))
    model.add(Activation(args.activation_function))
    if args.maxpool_after_n_layer > 0 and (i+1) % args.maxpool_after_n_layer == 0:
        model.add(MaxPooling2D(pool_size=(2, 2)))
        if args.dropout_factor_after_maxp > 0:
            model.add(Dropout(args.dropout_factor_after_maxp))
    elif args.dropout_factor_after_conv > 0:
        model.add(Dropout(args.dropout_factor_after_conv))

model.add(GlobalAveragePooling2D())
if args.dropout_factor_after_maxp > 0:
    model.add(Dropout(args.dropout_factor_after_maxp))


model.add(Flatten())
model.add(Dense(2))
model.add(Activation('softmax'))

#%%
optimizer = tf.keras.optimizers.Adam(args.learning_rate)
model.compile(loss='categorical_crossentropy', optimizer=optimizer, metrics=['accuracy',tf.keras.metrics.AUC()])
model.summary()

#%% md
data loader

#%%
def next_data_pcam(x,y,bz=args.batch_size):
    datalen = len(x)
    while True:
        indizies = None
        while indizies is None or len(indizies) == bz:
            indizies = np.unique(sorted(np.random.randint(datalen,size=bz)))
        
        x_data = np.array(x[indizies])
        if args.normalize_input:
            x_data = x_data/256.0
        if args.use_cropping:
            r = np.random.randint(10)
            r2 = np.random.randint(10)
            x_data = x_data[:,r:-10+r,r2:-10+r2]
        if args.flip_input:
            if np.random.randint(2) == 1:
                x_data = x_data[:,::-1]
            if np.random.randint(2) == 1:
                x_data = x_data[:,:,::-1]
        
        yield x_data, np.array([[1,0],[0,1]])[y[indizies][:,0,0,0]]
      
#%% dch
tmp = next(next_data_pcam(x_train, y_train))
print(tmp[0].shape)
print(tmp[1].shape)
        
#%% md
train the model

#%%
model.fit_generator(next_data_pcam(x_train, y_train),
                        validation_steps=validation_steps,
                        steps_per_epoch=steps_per_epoch,
                        epochs=args.num_of_epochs,
                        validation_data=next_data_pcam(x_valid, y_valid),workers=1, verbose=2)

#%%


#%%
#%%
#%% dch
import matplotlib.pyplot as plt
import seaborn
import numpy as np
samples = np.random.beta(1,1,size=100)
plt.hist(samples, bins=100);
#%%
