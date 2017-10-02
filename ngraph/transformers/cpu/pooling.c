/*******************************************************************************
* Copyright 2016 Intel Corporation
*
* Licensed under the Apache License, Version 2.0 (the "License");
* you may not use this file except in compliance with the License.
* You may obtain a copy of the License at
*
*     http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS,
* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
* See the License for the specific language governing permissions and
* limitations under the License.
*******************************************************************************/
#include "mkldnn_engine.h"
#include "mkldnn_util.h"

void create_mkldnn_pool_fprop_kernel(mkldnn_engine_t engine, int src_dims,
                                     int dst_dims, int* src_sizes,
                                     int* kernel_sizes, int* dst_sizes,
                                     int* strides, int* padding, int pool_type,
                                     mkldnn_memory_desc_t* input_src_md,
                                     mkldnn_data_type_t data_type,
                                     mkldnn_opkernel_t opkernel) {
  /* create data descriptors for pooling w/ no specified format */
  mkldnn_memory_desc_t mkldnn_memory_desc_src_md, mkldnn_memory_desc_dst_md;
  if (input_src_md) {
    mkldnn_memory_desc_src_md = *input_src_md;
  } else {
    MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_src_md, src_dims,
                                      src_sizes, data_type, mkldnn_chwn));
  }
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_dst_md, dst_dims,
                                    dst_sizes, data_type, mkldnn_any));

  /* create a pooling descriptor  - logical description of pooling */
  mkldnn_pooling_desc_t pool_any_desc;
  if (pool_type == 0) {
    MKL_CHECK(mkldnn_pooling_forward_desc_init(
        &pool_any_desc, mkldnn_forward_training, mkldnn_pooling_max,
        &mkldnn_memory_desc_src_md, &mkldnn_memory_desc_dst_md, strides,
        kernel_sizes, padding, padding, mkldnn_padding_zero));
  } else {
    MKL_CHECK(mkldnn_pooling_forward_desc_init(
        &pool_any_desc, mkldnn_forward_training, mkldnn_pooling_avg,
        &mkldnn_memory_desc_src_md, &mkldnn_memory_desc_dst_md, strides,
        kernel_sizes, padding, padding, mkldnn_padding_zero));
  }

  /* create a pooling primitive descriptor - pooling descriptor bound to the CPU
   * engine */
  MKL_CHECK(mkldnn_primitive_desc_create(&opkernel->op_desc, &pool_any_desc,
                                         engine, NULL));

  const_mkldnn_primitive_desc_t kernel_src_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_src_pd, 0);
  const_mkldnn_primitive_desc_t kernel_dst_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_dst_pd, 0);

  if (input_src_md) {
    create_mkldnn_tensor_from_md(src_dims, src_sizes, input_src_md, engine,
                                 &(opkernel->inputs[0]));
  } else {
    create_mkldnn_tensor(src_dims, src_sizes, data_type, mkldnn_chwn, engine,
                         &(opkernel->inputs[0]));
  }
  mkldnn_memory_desc_t dst_md =
      *mkldnn_primitive_desc_query_memory_d(kernel_dst_pd);
  create_mkldnn_tensor_from_md(dst_dims, dst_sizes, &dst_md, engine,
                               &(opkernel->outputs[0]));
  opkernel->num_inputs = 1;
  opkernel->num_outputs = 1;

  // No reorder on the input/output side
  opkernel->reorder_i[0] = NULL;
  opkernel->reorder_o[0] = NULL;

  // Workspace for max pooling
  if (pool_type == 0) {
    opkernel->num_outputs = 2;
    const_mkldnn_primitive_desc_t kernel_argmax_pd =
        mkldnn_primitive_desc_query_pd(opkernel->op_desc,
                                       mkldnn_query_workspace_pd, 0);
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_argmax_pd);
    create_mkldnn_tensor_from_md(dst_dims, dst_sizes, &md, engine,
                                 &(opkernel->outputs[1]));
    opkernel->reorder_o[1] = NULL;
  }

  const_mkldnn_primitive_t pool_dsts[2];
  pool_dsts[0] = opkernel->outputs[0].prim;
  if (pool_type == 0) pool_dsts[1] = opkernel->outputs[1].prim;
  mkldnn_primitive_at_t pool_srcs[] = {
      mkldnn_primitive_at(opkernel->inputs[0].prim, 0)};

  /* create a pooling primitive */
  MKL_CHECK(mkldnn_primitive_create(&opkernel->op_prim, opkernel->op_desc,
                                    pool_srcs, pool_dsts));
  opkernel->net[opkernel->net_size++] = opkernel->op_prim;
}

void create_mkldnn_pool_bprop_kernel(mkldnn_engine_t engine, int src_dims,
                                     int dst_dims, int* src_sizes,
                                     int* kernel_sizes, int* dst_sizes,
                                     int* strides, int* padding, int pool_type,
                                     mkldnn_memory_desc_t* input_src_md,
                                     mkldnn_data_type_t data_type,
                                     mkldnn_opkernel_t fprop_opkernel,
                                     mkldnn_opkernel_t opkernel) {
  /* create data descriptors for pooling w/ no specified format */
  mkldnn_memory_desc_t mkldnn_memory_desc_src_md, mkldnn_memory_desc_dst_md;
  if (input_src_md) {
    mkldnn_memory_desc_src_md = *input_src_md;
  } else {
    MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_src_md, src_dims,
                                      src_sizes, data_type, mkldnn_chwn));
  }
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_dst_md, dst_dims,
                                    dst_sizes, data_type, mkldnn_any));

  /* create a pooling descriptor  - logical description of pooling */
  mkldnn_pooling_desc_t pool_any_desc;
  if (pool_type == 0) {
    MKL_CHECK(mkldnn_pooling_backward_desc_init(
        &pool_any_desc, mkldnn_pooling_max, &mkldnn_memory_desc_dst_md,
        &mkldnn_memory_desc_src_md, strides, kernel_sizes, padding, padding,
        mkldnn_padding_zero));
  } else {
    MKL_CHECK(mkldnn_pooling_backward_desc_init(
        &pool_any_desc, mkldnn_pooling_avg, &mkldnn_memory_desc_dst_md,
        &mkldnn_memory_desc_src_md, strides, kernel_sizes, padding, padding,
        mkldnn_padding_zero));
  }

  /* create a pooling primitive descriptor - pooling descriptor bound to the CPU
   * engine */
  MKL_CHECK(mkldnn_primitive_desc_create(&opkernel->op_desc, &pool_any_desc,
                                         engine, fprop_opkernel->op_desc));

  const_mkldnn_primitive_desc_t kernel_src_pd = mkldnn_primitive_desc_query_pd(
      opkernel->op_desc, mkldnn_query_diff_dst_pd, 0);
  const_mkldnn_primitive_desc_t kernel_dst_pd = mkldnn_primitive_desc_query_pd(
      opkernel->op_desc, mkldnn_query_diff_src_pd, 0);

  if (input_src_md) {
    create_mkldnn_tensor_from_md(src_dims, src_sizes, input_src_md, engine,
                                 &(opkernel->inputs[0]));
  } else {
    create_mkldnn_tensor(src_dims, src_sizes, data_type, mkldnn_chwn, engine,
                         &(opkernel->inputs[0]));
  }
  mkldnn_memory_desc_t dst_md =
      *mkldnn_primitive_desc_query_memory_d(kernel_dst_pd);
  create_mkldnn_tensor_from_md(dst_dims, dst_sizes, &dst_md, engine,
                               &(opkernel->outputs[0]));
  opkernel->num_inputs = 1;
  opkernel->num_outputs = 1;

  // No reorder on the input/output side
  opkernel->reorder_i[0] = NULL;
  opkernel->reorder_o[0] = NULL;

  // Workspace for max pooling
  if (pool_type == 0) {
    opkernel->num_inputs = 2;
    const_mkldnn_primitive_desc_t kernel_argmax_pd =
        mkldnn_primitive_desc_query_pd(opkernel->op_desc,
                                       mkldnn_query_workspace_pd, 0);
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_argmax_pd);
    create_mkldnn_tensor_from_md(src_dims, src_sizes, &md, engine,
                                 &(opkernel->inputs[1]));
    opkernel->reorder_i[1] = NULL;
  }

  mkldnn_primitive_at_t pool_srcs[2];
  pool_srcs[0] = mkldnn_primitive_at(opkernel->inputs[0].prim, 0);
  if (pool_type == 0)
    pool_srcs[1] = mkldnn_primitive_at(opkernel->inputs[1].prim, 0);
  mkldnn_primitive_at_t pool_dsts[] = {
      mkldnn_primitive_at(opkernel->outputs[0].prim, 0)};

  /* create a pooling primitive */
  MKL_CHECK(mkldnn_primitive_create(&opkernel->op_prim, opkernel->op_desc,
                                    pool_srcs, pool_dsts));
  opkernel->net[opkernel->net_size++] = opkernel->op_prim;
}
