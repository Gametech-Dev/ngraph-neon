#!/usr/bin/env python
# ******************************************************************************
# Copyright 2017-2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ******************************************************************************

from __future__ import division, print_function
import sys
import numpy as np
import neon as ng
import neon.transformers as ngt
from neon.frontend import ax, NeonArgparser
from tqdm import tqdm
from data import make_aeon_loaders
from neon.frontend import GradientDescentMomentum
from neon.frontend import Layer
from resnet import BuildResnet
from contextlib import closing
from neon.frontend import Saver
from utils import get_network_params, set_lr


def open_csv(file_name, mode):
    """
    Open CSV file with right mode based on the py version
    """
    return(open(file_name, mode=mode + 'b') if sys.version_info[0] < 3 else
           open(file_name, mode=mode, newline=''))

# Calculate metrics over given dataset


def loop_eval(dataset, input_ph, metric_name, computation, en_top5=False):
    # Reset test set
    dataset.reset()
    all_results = None
    # Iterating over the dataset
    for data in dataset:
        feed_dict = {input_ph[k]: data[k] for k in data.keys()}
        # Tuple of results from computation
        results = computation(feed_dict=feed_dict)
        # Seperate Results
        results_miss_loss = results[1]
        results_inference = results[0]
        # Collect top5 and top1 results
        top5 = np.argsort(results_inference, axis=0)[-5:]
        top1 = top5[-1:]
        # Get ground truth labels
        correct_label = data['label'].T
        # Compare if any of the top5 matches with labels
        top5_results = np.any(np.equal(correct_label, top5), axis=0)
        # Invert for mis-classification
        top5_results = np.invert(top5_results)
        # Compare which are not equal
        top1_results = np.not_equal(correct_label, top1)
        # Make a list of results
        if(en_top5):
            total_results = [results_miss_loss, top5_results, top1_results]
        else:
            total_results = [results_miss_loss, top1_results]
        # Accumulate results
        if all_results is None:
            all_results = {name: list(res) for name, res in zip(metric_names, total_results)}
        else:
            for name, res in zip(metric_names, total_results):
                all_results[name].extend(list(res))
    # Take mean of results
    ndata = dataset.ndata
    reduced_results = {k: np.mean(v[:ndata]) for k, v in all_results.items()}
    return reduced_results


if __name__ == "__main__":
    # Hyperparameters
    # Optimizer
    base_lr = 0.1
    gamma = 0.1
    momentum_coef = 0.9
    wdecay = 0.0001
    nesterov = False

    print("HyperParameters")
    print("Learning Rate:     " + str(base_lr))
    print("Momentum:          " + str(momentum_coef))
    print("Weight Decay:      " + str(wdecay))
    print("Nesterov:          " + str(nesterov))

    # Command Line Parser
    parser = NeonArgparser(description="Resnet for Imagenet and Cifar10")
    parser.add_argument('--dataset', type=str, default="cifar10", help="Enter cifar10 or i1k")
    parser.add_argument('--size', type=int, default=56, help="Enter size of resnet")
    parser.add_argument('--logfile', type=str, default=None, help="Name of the csv which \
                        logs different metrics of model")
    parser.add_argument('--disable_batch_norm', action='store_true')
    parser.add_argument('--save_file', type=str, default=None, help="File to save weights")
    parser.add_argument('--inference', type=str, default=None, help="File to load weights")
    parser.add_argument('--resume', type=str, default=None, help="Weights file to resume training")
    args = parser.parse_args()

# Initialize seed before any use
np.random.seed(args.rng_seed)

# Get network parameters
nw_params = get_network_params(args.dataset, args.size, args.batch_size)
metric_names = nw_params['metric_names']
en_top5 = nw_params['en_top5']
num_resnet_mods = nw_params['num_resnet_mods']
args.iter_interval = nw_params['iter_interval']
learning_schedule = nw_params['learning_schedule']
en_bottleneck = nw_params['en_bottleneck']
ax.Y.length = nw_params['num_classes']

# Set batch size
ax.N.length = args.batch_size
# Create training and validation set objects
train_set, valid_set = make_aeon_loaders(args.data_dir, args.batch_size,
                                         args.num_iterations, dataset=args.dataset)
print("Completed loading " + args.dataset + " dataset")
# Randomize seed
np.random.seed(args.rng_seed)
# Make placeholders
input_ph = train_set.make_placeholders(include_iteration=True)

# Build the network
resnet = BuildResnet(args.dataset, args.size, en_bottleneck, num_resnet_mods,
                     batch_norm=not args.disable_batch_norm)

# Learning Rate Placeholder
lr_ph = ng.placeholder(axes=(), initial_value=base_lr)

# Optimizer
# Provided learning policy takes learning rate as input to graph using a placeholder.
# This allows you to control learning rate based on various factors of network
learning_rate_policy = {'name': 'provided',
                        'lr_placeholder': lr_ph}

optimizer = GradientDescentMomentum(learning_rate=learning_rate_policy,
                                    momentum_coef=momentum_coef,
                                    wdecay=wdecay,
                                    nesterov=False,
                                    iteration=input_ph['iteration'])
label_indices = input_ph['label']
# Make a prediction
prediction = resnet(input_ph['image'])
# Calculate loss
train_loss = ng.cross_entropy_multi(prediction, ng.one_hot(label_indices, axis=ax.Y))
# Average loss over the batch
batch_cost = ng.sequential([optimizer(train_loss), ng.mean(train_loss, out_axes=())])
train_computation = ng.computation(batch_cost, "all")

# Instantiate the Saver object to save weights
weight_saver = Saver()

# Inference
with Layer.inference_mode_on():
    # Doing inference
    inference_prob = resnet(input_ph['image'])
    eval_loss = ng.cross_entropy_multi(inference_prob, ng.one_hot(label_indices, axis=ax.Y))
    # Computation for inference
    eval_computation = ng.computation([inference_prob, eval_loss], "all")

# Doing inference
if(args.inference is not None):
    with closing(ngt.make_transformer()) as transformer:
        restore_eval_function = transformer.add_computation(eval_computation)
        weight_saver.setup_restore(transformer=transformer, computation=eval_computation,
                                   filename=args.inference)
        # Restore weight
        weight_saver.restore()
        # Calculate losses
        eval_losses = loop_eval(valid_set, input_ph, metric_names, restore_eval_function, en_top5)
        # Print statistics
        print("From restored weights: Test Avg loss:{tcost}".format(tcost=eval_losses))
        exit()

# Training the network by calling transformer
with closing(ngt.make_transformer_factory(args.backend)()) as transformer:
    # Trainer
    train_function = transformer.add_computation(train_computation)
    # Inference
    eval_function = transformer.add_computation(eval_computation)
    # Set Saver for saving weights
    weight_saver.setup_save(transformer=transformer, computation=train_computation)
    # Resume weights for training from a checkpoint
    if args.resume is not None:
        weight_saver.setup_restore(transformer=transformer, computation=train_computation,
                                   filename=args.resume)
        weight_saver.restore()
    # Progress bar
    tpbar = tqdm(unit="batches", ncols=100, total=args.num_iterations)
    # Set interval cost to 0.0
    interval_cost = 0.0
    # Declare lists for logging metrics
    if(args.logfile is not None):
        train_result = []
        test_result = []
        err_result = []
    # Iterating over the training set
    for step, data in enumerate(train_set):
        data['iteration'] = step
        # Dictionary for training
        feed_dict = {input_ph[k]: data[k] for k in input_ph.keys()}
        # Learning Schedule
        feed_dict[lr_ph] = set_lr(base_lr, step, learning_schedule, gamma)
        # Mean batch cost
        output = train_function(feed_dict=feed_dict)
        # Update progress bar
        tpbar.update(1)
        tpbar.set_description("Training {:0.4f}".format(output[()]))
        interval_cost += output[()]
        # Every epoch print test set metrics
        if (step + 1) % args.iter_interval == 0 and step > 0:
            # Call loop_eval to calculate metric over test set
            eval_losses = loop_eval(valid_set, input_ph, metric_names, eval_function, en_top5)
            tqdm.write("Interval {interval} Iteration {iteration} complete. "
                       "Avg Train Cost {cost:0.4f} Test Metrics:{tcost}".format(
                           interval=step // args.iter_interval,
                           iteration=step,
                           cost=interval_cost / args.iter_interval, tcost=eval_losses))
            # Log metrics to list
            if(args.logfile is not None):
                # For storing to csv
                train_result.append(interval_cost / args.iter_interval)
                test_result.append(eval_losses['Cross_Ent_Loss'])
                if args.dataset == 'cifar10':
                    err_result.append(eval_losses['Misclass'])
                if args.dataset == 'i1k':
                    err_result.append(eval_losses['Top5_Err'])
            interval_cost = 0.0
            if(args.save_file is not None):
                print("\nSaving Weights")
                weight_saver.save(filename=args.save_file + "_" + str(step))
    # Writing to CSV
    if(args.logfile is not None):
        print("\nSaving results to csv file")
        import csv
        with open_csv(args.logfile + ".csv", 'w') as train_test_file:
            wr = csv.writer(train_test_file, quoting=csv.QUOTE_ALL)
            wr.writerow(train_result)
            wr.writerow(test_result)
            wr.writerow(err_result)
    print("\nTraining Completed")
    if(args.save_file is not None):
        print("\nSaving Weights")
        weight_saver.save(filename=args.save_file)
