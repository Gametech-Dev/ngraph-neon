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
import os
import numpy as np
from PIL import Image
from tqdm import tqdm
from neon.frontend.aeon_shim import AeonDataLoader
from neon.util.persist import get_data_cache_or_nothing
from neon.frontend import CIFAR10, CIFAR100


def ingest_cifar100(root_dir, overwrite=False):
    '''
    Save CIFAR-100 dataset as PNG files
    '''
    out_dir = os.path.join(root_dir, 'cifar100')

    set_names = ('train', 'valid')
    manifest_files = [os.path.join(out_dir, setn + '-index.csv') for setn in set_names]

    if (all([os.path.exists(manifest) for manifest in manifest_files]) and not overwrite):
        return manifest_files

    datasets = CIFAR100(out_dir).load_data()

    # Now write out image files and manifests
    for setn, manifest, data in zip(set_names, manifest_files, datasets):
        records = [('@FILE', 'STRING')]
        img_path = os.path.join(out_dir, setn)
        if not os.path.isdir(img_path):
            os.makedirs(img_path)

        for idx, (img, lbl) in enumerate(tqdm(zip(data['image']['data'], data['label']['data']))):
            im = Image.fromarray(np.uint8(np.transpose(img, axes=[1, 2, 0]).copy()))
            fname = os.path.join(img_path, '{}_{:05d}.png'.format(lbl, idx))
            im.save(fname, format='PNG')
            records.append((os.path.relpath(fname, out_dir), lbl))
        np.savetxt(manifest, records, fmt='%s\t%s')

    return manifest_files


def ingest_cifar10(root_dir, overwrite=False):
    '''
    Save CIFAR-10 dataset as PNG files
    '''
    out_dir = os.path.join(root_dir, 'cifar10')

    set_names = ('train', 'valid')
    manifest_files = [os.path.join(out_dir, setn + '-index.csv') for setn in set_names]

    if (all([os.path.exists(manifest) for manifest in manifest_files]) and not overwrite):
        return manifest_files

    datasets = CIFAR10(out_dir).load_data()

    # Now write out image files and manifests
    for setn, manifest, data in zip(set_names, manifest_files, datasets):
        records = [('@FILE', 'STRING')]
        img_path = os.path.join(out_dir, setn)
        if not os.path.isdir(img_path):
            os.makedirs(img_path)

        for idx, (img, lbl) in enumerate(tqdm(zip(data['image']['data'], data['label']['data']))):
            im = Image.fromarray(np.uint8(np.transpose(img, axes=[1, 2, 0]).copy()))
            fname = os.path.join(img_path, '{}_{:05d}.png'.format(lbl, idx))
            im.save(fname, format='PNG')
            records.append((os.path.relpath(fname, out_dir), lbl))
        np.savetxt(manifest, records, fmt='%s\t%s')

    return manifest_files


def make_aeon_loaders(work_dir, batch_size, train_iterations, random_seed=0, dataset="cifar10"):
    # Generating manifests for different datasets
    if(dataset == "cifar10"):
        train_manifest, valid_manifest = ingest_cifar10(work_dir)
    elif(dataset == "cifar100"):
        train_manifest, valid_manifest = ingest_cifar100(work_dir)
    elif(dataset == "i1k"):
        path = str(os.environ['BASE_DATA_DIR'])
        train_manifest, valid_manifest = path + "train-index.csv", path + "val-index.csv"
    elif(dataset == "i1k100"):
        path = str(os.environ['BASE_DATA_DIR'])
        train_manifest, valid_manifest = path + "train-index-100.csv", path + "val-index-100.csv"
    else:
        raise NameError("Unkown dataset.Choose either cifar10 or i1k dataset")
        exit()

    def common_config(manifest_file, batch_size, valid_set=False):
        if(dataset == "cifar10"):
            # Define Cache
            cache_root = get_data_cache_or_nothing('cifar10-cache/')
            # Define image properties
            image_config = {"type": "image",
                            "height": 32,
                            "width": 32}
            # Define label properties
            label_config = {"type": "label",
                            "binary": False}
            # Define Augmentations
            augmentation = {"type": "image",
                            "padding": 4,
                            "crop_enable": False,
                            "flip_enable": True}
            # Don't enable augmentations if it is test set
            if(valid_set):
                return {'manifest_filename': manifest_file,
                        'manifest_root': os.path.dirname(manifest_file),
                        'batch_size': batch_size,
                        'block_size': 5000,
                        'cache_directory': cache_root,
                        'etl': [image_config, label_config]}
            return {'manifest_filename': manifest_file,
                    'manifest_root': os.path.dirname(manifest_file),
                    'batch_size': batch_size,
                    'block_size': 5000,
                    'cache_directory': cache_root,
                    'etl': [image_config, label_config],
                    'augmentation': [augmentation]}
        elif(dataset == "i1k"):
            # Define cache
            cache_root = get_data_cache_or_nothing("i1k-cache/")
            # Define image properties
            image_config = {"type": "image",
                            "height": 224,
                            "width": 224}
            # Define label properties
            label_config = {"type": "label",
                            "binary": False}
            # Define Augmentations
            augmentation = {"type": "image",
                            "center": False,
                            "flip_enable": True,
                            "scale": [0.08, 1.0],
                            "do_area_scale": True,
                            "horizontal_distortion": [0.75, 1.33],
                            "lighting": [0.0, 0.01],
                            "contrast": [0.9, 1.1],
                            "brightness": [0.9, 1.1],
                            "saturation": [0.9, 1.1]
                            }
            # Dont do augemtations on test set
            if(valid_set):
                return{'manifest_filename': manifest_file,
                       'manifest_root': os.path.dirname(manifest_file),
                       'batch_size': batch_size,
                       'block_size': 5000,
                       'cache_directory': cache_root,
                       'etl': [image_config, label_config]}
            # Do augmentations on training set
            return{'manifest_filename': manifest_file,
                   'manifest_root': os.path.dirname(manifest_file),
                   'batch_size': batch_size,
                   'block_size': 5000,
                   'cache_directory': cache_root,
                   'etl': [image_config, label_config],
                   'augmentation': [augmentation]}
        elif(dataset == "cifar100"):
            # Define Cache
            cache_root = get_data_cache_or_nothing('cifar100-cache/')
            # Define image properties
            image_config = {"type": "image",
                            "height": 32,
                            "width": 32}
            # Define label properties
            label_config = {"type": "label",
                            "binary": False}
            # Define Augmentations
            augmentation = {"type": "image",
                            "padding": 4,
                            "crop_enable": False,
                            "flip_enable": True}
            # Don't enable augmentations if it is test set
            if(valid_set):
                return {'manifest_filename': manifest_file,
                        'manifest_root': os.path.dirname(manifest_file),
                        'batch_size': batch_size,
                        'block_size': 5000,
                        'cache_directory': cache_root,
                        'etl': [image_config, label_config]}
            return {'manifest_filename': manifest_file,
                    'manifest_root': os.path.dirname(manifest_file),
                    'batch_size': batch_size,
                    'block_size': 5000,
                    'cache_directory': cache_root,
                    'etl': [image_config, label_config],
                    'augmentation': [augmentation]}
        elif(dataset == "i1k100"):
            # Define cache
            cache_root = get_data_cache_or_nothing("i1k-cache/")
            # Define image properties
            image_config = {"type": "image",
                            "height": 224,
                            "width": 224}
            # Define label properties
            label_config = {"type": "label",
                            "binary": False}
            # Define Augmentations
            augmentation = {"type": "image",
                            "center": False,
                            "flip_enable": True,
                            "scale": [0.08, 1.0],
                            "do_area_scale": True,
                            "horizontal_distortion": [0.75, 1.33],
                            "lighting": [0.0, 0.01],
                            "contrast": [0.9, 1.1],
                            "brightness": [0.9, 1.1],
                            "saturation": [0.9, 1.1]
                            }
            # Dont do augemtations on test set
            if(valid_set):
                return{'manifest_filename': manifest_file,
                       'manifest_root': os.path.dirname(manifest_file),
                       'batch_size': batch_size,
                       'block_size': 5000,
                       'cache_directory': cache_root,
                       'etl': [image_config, label_config]}
            # Do augmentations on training set
            return{'manifest_filename': manifest_file,
                   'manifest_root': os.path.dirname(manifest_file),
                   'batch_size': batch_size,
                   'block_size': 5000,
                   'cache_directory': cache_root,
                   'etl': [image_config, label_config],
                   'augmentation': [augmentation]}
        else:
            raise NameError("Unkown dataset.Choose correct dataset")

    train_config = common_config(train_manifest, batch_size)
    train_config['iteration_mode'] = "COUNT"
    train_config['iteration_mode_count'] = train_iterations
    train_config['shuffle_manifest'] = True
    train_config['shuffle_enable'] = True
    train_config['random_seed'] = random_seed

    valid_config = common_config(valid_manifest, batch_size, valid_set=True)
    valid_config['iteration_mode'] = "ONCE"

    train_loader = AeonDataLoader(train_config)
    valid_loader = AeonDataLoader(valid_config)

    return (train_loader, valid_loader)
