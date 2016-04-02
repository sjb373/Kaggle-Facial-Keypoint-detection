from __future__ import print_function

import sys
import os
import time
import string
import random
import pickle

import numpy as np
import theano
import theano.tensor as T
import lasagne

import cPickle as pickle
from datetime import datetime
import os
import sys
from lasagne.layers.dnn import Conv2DDNNLayer as ConvLayer
from lasagne.layers import ElemwiseSumLayer
from lasagne.layers import InputLayer
from lasagne.layers import DenseLayer
from lasagne.layers import GlobalPoolLayer
from lasagne.layers import PadLayer
from lasagne.layers import ExpressionLayer
from lasagne.layers import NonlinearityLayer
from lasagne.nonlinearities import softmax, rectify
from lasagne.layers import batch_norm

from matplotlib import pyplot
import numpy as np
from lasagne import layers
from nolearn.lasagne import BatchIterator
from nolearn.lasagne import NeuralNet
from pandas import DataFrame
from pandas.io.parsers import read_csv
from sklearn.utils import shuffle
import theano

try:
	from lasagne.layers.cuda_convnet import Conv2DCCLayer as Conv2DLayer
	from lasagne.layers.cuda_convnet import MaxPool2DCCLayer as MaxPool2DLayer
	from lasagne.nonlinearities import elu
except ImportError:
	Conv2DLayer = layers.Conv2DLayer
	MaxPool2DLayer = layers.MaxPool2DLayer
	 

sys.setrecursionlimit(99000)  # for pickle...
np.random.seed(42)

FTRAIN = '/home/soren/Desktop/KFKD/kfkd-tutorial-master/training.csv'
FTEST = '/home/soren/Desktop/KFKD/test.csv'
FLOOKUP = '/home/soren/Desktop/KFKD/kfkd-tutorial-master/IdLookupTable.csv'



def float32(k):
	return np.cast['float32'](k)


def load(test=False, cols=None):
	"""Loads data from FTEST if *test* is True, otherwise from FTRAIN.
	Pass a list of *cols* if you're only interested in a subset of the
	target columns.
	"""
	fname = FTEST if test else FTRAIN
	df = read_csv(os.path.expanduser(fname))  # load pandas dataframe

	# The Image column has pixel values separated by space; convert
	# the values to numpy arrays:
	df['Image'] = df['Image'].apply(lambda im: np.fromstring(im, sep=' '))

	if cols:  # get a subset of columns
		df = df[list(cols) + ['Image']]

	print(df.count())  # prints the number of values for each column
	df = df.dropna()  # drop all rows that have missing values in them

	X = np.vstack(df['Image'].values) / 255.  # scale pixel values to [0, 1]
	X = X.astype(np.float32)

	if not test:  # only FTRAIN has any target columns
		y = df[df.columns[:-1]].values
		y = (y - 48) / 48  # scale target coordinates to [-1, 1]
		X, y = shuffle(X, y, random_state=42)  # shuffle train data
		y = y.astype(np.float32)
	else:
		y = None
	
	return X, y


def load2d(test=False, cols=None):
	print('loading 2d data')
	X, y = load(test=test, cols=cols)
	X = X.reshape(-1, 1, 96, 96)
	print('finished loading data')
	return X, y


def plot_sample(x, y, axis):
	img = x.reshape(96, 96)
	axis.imshow(img, cmap='gray')
	if y is not None:
		axis.scatter(y[0::2] * 48 + 48, y[1::2] * 48 + 48, marker='x', s=10)


def plot_weights(weights):
	fig = pyplot.figure(figsize=(6, 6))
	fig.subplots_adjust(
		left=0, right=1, bottom=0, top=1, hspace=0.05, wspace=0.05)

	for i in range(16):
		ax = fig.add_subplot(4, 4, i + 1, xticks=[], yticks=[])
		ax.imshow(weights[:, i].reshape(96, 96), cmap='gray')
	pyplot.show()


class FlipBatchIterator(BatchIterator):
	flip_indices = [
		(0, 2), (1, 3),
		(4, 8), (5, 9), (6, 10), (7, 11),
		(12, 16), (13, 17), (14, 18), (15, 19),
		(22, 24), (23, 25),
		]

	def transform(self, Xb, yb):
		Xb, yb = super(FlipBatchIterator, self).transform(Xb, yb)

		# Flip half of the images in this batch at random:
		bs = Xb.shape[0]
		indices = np.random.choice(bs, bs / 2, replace=False)
		Xb[indices] = Xb[indices, :, :, ::-1]

		if yb is not None:
			# Horizontal flip of all x coordinates:
			yb[indices, ::2] = yb[indices, ::2] * -1

			# Swap places, e.g. left_eye_center_x -> right_eye_center_x
			for a, b in self.flip_indices:
				yb[indices, a], yb[indices, b] = (
					yb[indices, b], yb[indices, a])

		return Xb, yb


class AdjustVariable(object):
	def __init__(self, name, start=0.03, stop=0.001):
		self.name = name
		self.start, self.stop = start, stop
		self.ls = None

	def __call__(self, nn, train_history):
		if self.ls is None:
			self.ls = np.linspace(self.start, self.stop, nn.max_epochs)
		#print('current'+self.name+str(getattr(nn,self.name)))
		epoch = train_history[-1]['epoch']
		new_value = np.cast['float32'](self.ls[epoch - 1])
		getattr(nn, self.name).set_value(new_value)


class EarlyStopping(object):
	def __init__(self, patience=100):
		self.patience = patience
		self.best_valid = np.inf
		self.best_valid_epoch = 0
		self.best_weights = None

	def __call__(self, nn, train_history):
		current_valid = train_history[-1]['valid_loss']
		current_epoch = train_history[-1]['epoch']
		if current_valid < self.best_valid:
			self.best_valid = current_valid
			self.best_valid_epoch = current_epoch
			self.best_weights = nn.get_all_params_values()
		elif self.best_valid_epoch + self.patience < current_epoch:
			print("Early stopping.")
			print("Best valid loss was {:.6f} at epoch {}.".format(
				self.best_valid, self.best_valid_epoch))
			nn.load_params_from(self.best_weights)
			raise StopIteration()
from lasagne import nonlinearities
#from lasagne.non
#custom_rectify = LeakyRectify(0.1)

from lasagne.layers import DropoutLayer
from lasagne.nonlinearities import very_leaky_rectify



def build_cnn(input_var=None, n=5,output_n=30):
	print('building cnn')
	#counter for number of dropout layers
	# create a residual learning building block with two stacked 3x3 convlayers as in paper
	def residual_block(l, increase_dim=False, projection=False,dropout=0):
		kwargz={};dn=0
		a=layers.DropoutLayer(l,p=dropout)
		input_num_filters = l.output_shape[1]
		if increase_dim:
			first_stride = (2,2)
			out_num_filters = input_num_filters*2
		else:
			first_stride = (1,1)
			out_num_filters = input_num_filters

		stack_1 = batch_norm(ConvLayer(
			a, 
			num_filters=out_num_filters, 
			filter_size=(3,3), 
			stride=first_stride, 
			nonlinearity=nonlinearities.very_leaky_rectify, 
			pad='same', 
			W=lasagne.init.HeNormal(gain='relu')
			))
		if dropout > 0:
			dn+=1
			dropOut1=layers.DropoutLayer(
				incoming=stack_1,
				p=dropout,
				)
			kwargz[str(dn)]=dropout
			stack_2 = batch_norm(ConvLayer(
				dropOut1, 
				num_filters=out_num_filters,
				filter_size=(3,3),
				stride=(1,1),
				nonlinearity=very_leaky_rectify,
				pad='same',
				W=lasagne.init.HeNormal(gain='relu'),
				))
		else:
			stack_2 = batch_norm(ConvLayer(
				stack_1,
				num_filters=out_num_filters,
				filter_size=(3,3),
				stride=(1,1),
				nonlinearity=very_leaky_rectify,
				pad='same',
				W=lasagne.init.HeNormal(gain='relu')
				))

		# add shortcut connections
		if increase_dim:
			if projection:
				# projection shortcut, as option B in paper
				projection = batch_norm(ConvLayer(l, num_filters=out_num_filters, filter_size=(1,1), stride=(2,2), nonlinearity=None, pad='same', b=None))
				block = NonlinearityLayer(ElemwiseSumLayer([stack_2, projection]),nonlinearity=very_leaky_rectify)
			else:
				# identity shortcut, as option A in paper
				identity = ExpressionLayer(l, lambda X: X[:, :, ::2, ::2], lambda s: (s[0], s[1], s[2]//2, s[3]//2))
				padding = PadLayer(identity, [out_num_filters//4,0,0], batch_ndim=1)
				block = NonlinearityLayer(
					ElemwiseSumLayer([stack_2, padding]),
					nonlinearity=very_leaky_rectify
					)
		else:
			block = NonlinearityLayer(ElemwiseSumLayer([stack_2, l]),nonlinearity=very_leaky_rectify)
		
		return block

	# Building the network
	l_in = InputLayer(shape=(None,1, 96, 96), input_var=input_var)

	# first layer, output is 16 x 32 x 32
	l = batch_norm(ConvLayer(l_in, num_filters=4, filter_size=(3,3), stride=(1,1), nonlinearity=very_leaky_rectify, pad='same', W=lasagne.init.HeNormal(gain='relu')))
	# first stack of residual blocks, output is 16 x 32 x 32
	for _ in range(n):
		l = residual_block(l,dropout=0.01)
	print ('first residual stack built')
	# second stack of residual blocks, output is 32 x 16 x 16
	l = residual_block(l, increase_dim=True,dropout=0.01)
	for _ in range(1,n):
		l = residual_block(l,dropout=0.01)
	print('second residual stack built')

	# third stack of residual blocks, output is 64 x 8 x 8
	l = residual_block(l, increase_dim=True,dropout=0.01)
	for _ in range(1,n):
		l = residual_block(l,dropout=0.01)
	print('third residual stack built')


	l = residual_block(l, increase_dim=True,dropout=0.01)
	for _ in range(1,n):
		l = residual_block(l,dropout=0.01)
	print('fourth residual stack built')

	l = residual_block(l, increase_dim=True,dropout=0.01)
	for _ in range(1,n):
		l = residual_block(l,dropout=0.1)
	print('fifth residual stack built')

	l = residual_block(l, increase_dim=True,dropout=0.1)
	for _ in range(1,n):
		l = residual_block(l,dropout=0.01)
	print('sixth residual stack built')
	

	
	# average pooling
	l = GlobalPoolLayer(l)
	l=DropoutLayer(l,p=0.03)
	l=DenseLayer(l,num_units=256,nonlinearity=very_leaky_rectify)
	
	# fully connected layer
	network = DenseLayer(
			l, num_units=output_n,
			W=lasagne.init.HeNormal(),
			nonlinearity=None)

	return network
print('ready to build cnn')
from lasagne.objectives import squared_error
network=build_cnn(
	input_var=None,
	n=1
	)
#for lyr in  lasagne.layers.get_all_layers(network):

  #  if 'Dropout' in str(type(lyr)):
   #     lyr.p=0
from nolearn.lasagne import visualize as v


def example_occ(n,X,target,sqrL=7,figsize=(9,None)):
	x1=X[n,:,:,:];x1=x1.reshape(1,1,96,96)*-1
	t1=target[n,:]
	v.plot_occlusion(net,x1,t1,sqrL,figsize)
	pyplot.show()

def ex_sal(a,b,X,size=(9,None)):
	plot_saliency(net,X[a:b,:,:,:],size)





	#print(str(lyr) + str(dir(lyr)))
class ActivateDropout(object):
	def __init__(self,doList,verbose=False,threshold=0.004,adjust_lr=False):
		self.doList=doList
		self.verbose=verbose
		self.threshold=threshold
		self.adjust_lr=adjust_lr
	def __call__(self,nn,train_history):
		current_valid = train_history[-1]['valid_loss']
		if np.mean(current_valid) <= self.threshold:
			i=0;
			for lyr in lasagne.layers.get_all_layers(nn.layers[0]):
				if 'Dropout' in str(type(lyr)):
					if lyr.p!=0:
						break
					lyr.p=self.doList[i]
					if self.verbose:
						print('p adjusted to ' +str(lyr.p))
					i+=1
			if self.adjust_lr:
				print('lr adjustment not ready yet')
			#    lr=getattr(nn,'update_learning_rate')

def l2Nesterov(loss_or_grads,params,learning_rate,momentum=0.9,reg=0.001):
	updates=nesterov_momentum(loss_or_grads,params,learning_rate,momentum)
	 

def get_NN(output_n=30,LRi=0.0001):
	net = NeuralNet(
	layers=[build_cnn(input_var=None,n=1,output_n=output_n)],
	#input_shape=(None, 1, 96, 96),
	update_learning_rate=theano.shared(float32(LRi)),
	update_momentum=theano.shared(float32(0.96)),
	regression=True,
	batch_iterator_train=FlipBatchIterator(batch_size=50),
	on_epoch_finished=[
		AdjustVariable('update_learning_rate', start=LRi, stop=0.000005),
		AdjustVariable('update_momentum', start=0.96, stop=0.9999),
	   #print('?')THESE DONT WORK. YOU HAVE TO DEFINE A CLASS FOR THESE
		#on_epoch_finished_test(),
		#SaveWeights(path='PATH_HERE',every_n_epochs=10,only_best=True)
		
		],
	max_epochs=1000,
	verbose=1,
	#objective_loss_function=squaredErrorL2Loss,
	#custom_scores=[('no L2 Val Loss',squared_error)],
	)
	return net

from collections import OrderedDict

from sklearn.base import clone


SPECIALIST_SETTINGS = [
    dict(
        columns=(
            'left_eye_center_x', 'left_eye_center_y',
            'right_eye_center_x', 'right_eye_center_y',
            ),
        flip_indices=((0, 2), (1, 3)),
        ),

    dict(
        columns=(
            'nose_tip_x', 'nose_tip_y',
            ),
        flip_indices=(),
        ),

    dict(
        columns=(
            'mouth_left_corner_x', 'mouth_left_corner_y',
            'mouth_right_corner_x', 'mouth_right_corner_y',
            'mouth_center_top_lip_x', 'mouth_center_top_lip_y',
            ),
        flip_indices=((0, 2), (1, 3)),
        ),

    dict(
        columns=(
            'mouth_center_bottom_lip_x',
            'mouth_center_bottom_lip_y',
            ),
        flip_indices=(),
        ),

    dict(
        columns=(
            'left_eye_inner_corner_x', 'left_eye_inner_corner_y',
            'right_eye_inner_corner_x', 'right_eye_inner_corner_y',
            'left_eye_outer_corner_x', 'left_eye_outer_corner_y',
            'right_eye_outer_corner_x', 'right_eye_outer_corner_y',
            ),
        flip_indices=((0, 2), (1, 3), (4, 6), (5, 7)),
        ),

    dict(
        columns=(
            'left_eyebrow_inner_end_x', 'left_eyebrow_inner_end_y',
            'right_eyebrow_inner_end_x', 'right_eyebrow_inner_end_y',
            'left_eyebrow_outer_end_x', 'left_eyebrow_outer_end_y',
            'right_eyebrow_outer_end_x', 'right_eyebrow_outer_end_y',
            ),
        flip_indices=((0, 2), (1, 3), (4, 6), (5, 7)),
        ),
    ]
net=build_cnn()
import dill as pickle
def fit_specialists(fname_pretrain=None):
    if fname_pretrain:
        with open(fname_pretrain, 'rb') as f:
            net_pretrain = pickle.load(f)

    else:
        net_pretrain = None

    specialists = OrderedDict()
    i=1
    for setting in SPECIALIST_SETTINGS:
        cols = setting['columns']
        X, y = load2d(cols=cols)
        #print('x.shape', X.shape)
        #print('y.shape:', y.shape)
        model=get_NN(output_n=y.shape[1],LRi=0.003)

        model.output_num_units = y.shape[1]
        print('initial LR =',getattr(model,'update_learning_rate').get_value())

        model.batch_iterator_train.flip_indices = setting['flip_indices']
        
        model.max_epochs = int(1e7 / y.shape[0])
        #model.max_epochs=3
        if 'kwargs' in setting:
            # an option 'kwargs' in the settings list may be used to
            # set any other parameter of the net:
            vars(model).update(setting['kwargs'])

        if net_pretrain is not None:
            # if a pretrain model was given, use it to initialize the
            # weights of our new specialist model:
            model.load_params_from(net_pretrain)
            print('pretrain loaded')
       
        print("Training model for columns {} for {} epochs".format(
            cols, model.max_epochs))
        print('this is the {}th column to be trained'.format(i))
        model.fit(X, y)
        specialists[cols] = model
        i+=1
    return specialists
    with open('net-specialists.pickle', 'wb') as f:
        # this time we're persisting a dictionary with all models:
        dill.dump(specialists, f, -1)



def predict(fname_specialists='net-specialists.pickle'):
    #print('ready')
    with open(fname_specialists, 'rb') as f:
        specialists = dill.load(f)
    print('specialists loaded')
    X = load2d(test=True)[0]
    print('data loaded')
    y_pred = np.empty((X.shape[0], 0))
        
    for model in specialists.values():
        y_pred1 = model.predict(X)
        print('finished a prediction')
        y_pred = np.hstack([y_pred, y_pred1])
    print('predictions finished')
    columns = ()
    for cols in specialists.keys():
        columns += cols

    y_pred2 = y_pred * 48 + 48
    y_pred2 = y_pred2.clip(0, 96)
    df = DataFrame(y_pred2, columns=columns)

    lookup_table = read_csv(os.path.expanduser(FLOOKUP))
    values = []

    for index, row in lookup_table.iterrows():
        values.append((
            row['RowId'],
            df.ix[row.ImageId - 1][row.FeatureName],
            ))

    now_str = datetime.now().isoformat().replace(':', '-')
    submission = DataFrame(values, columns=('RowId', 'Location'))
    filename = 'submission-{}.csv'.format(now_str)
    submission.to_csv(filename, index=False)
    print("Wrote {}".format(filename))


def rebin(a, newshape ):
    from numpy import mgrid
    assert len(a.shape) == len(newshape)

    slices = [ slice(0,old, float(old)/new) for old,new in zip(a.shape,newshape) ]
    coordinates = mgrid[slices]
    indices = coordinates.astype('i')   #choose the biggest smaller integer index
    return a[tuple(indices-1)]


def plot_learning_curves(fname_specialists='net-specialists.pickle'):
    with open(fname_specialists, 'r') as f:
        models = dill.load(f)

    fig = pyplot.figure(figsize=(10, 6))
    ax = fig.add_subplot(1, 1, 1)
    ax.set_color_cycle(
        ['c', 'c', 'm', 'm', 'y', 'y', 'k', 'k', 'g', 'g', 'b', 'b'])

    valid_losses = []
    train_losses = []

    for model_number, (cg, model) in enumerate(models.items(), 1):
        valid_loss = np.array([i['valid_loss'] for i in model.train_history_])
        train_loss = np.array([i['train_loss'] for i in model.train_history_])
        valid_loss = np.sqrt(valid_loss) * 48
        train_loss = np.sqrt(train_loss) * 48

        valid_loss = rebin(valid_loss, (100,))
        train_loss = rebin(train_loss, (100,))

        valid_losses.append(valid_loss)
        train_losses.append(train_loss)
        ax.plot(valid_loss,
                label='{} ({})'.format(cg[0], len(cg)), linewidth=3)
        ax.plot(train_loss,
                linestyle='--', linewidth=3, alpha=0.6)
        ax.set_xticks([])

    weights = np.array([m.output_num_units for m in models.values()],
                       dtype=float)
    weights /= weights.sum()
    mean_valid_loss = (
        np.vstack(valid_losses) * weights.reshape(-1, 1)).sum(axis=0)
    ax.plot(mean_valid_loss, color='r', label='mean', linewidth=4, alpha=0.8)

    ax.legend()
    ax.set_ylim((1.0, 4.0))
    ax.grid()
    pyplot.ylabel("RMSE")
    pyplot.show()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
    else:
        func = globals()[sys.argv[1]]
        func(*sys.argv[2:])
