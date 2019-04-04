# Import the example classes
from mylab.rewards.heuristic_reward import HeuristicReward
from mylab.spaces.example_av_spaces import ExampleAVSpaces
from mylab.rewards.pedestrian_noise_gaussian import PedestrianNoiseGaussian

# Import RSS stuff
from mylab.simulators.av_rss_simulator import AVRSSSimulator
import mylab.simulators.rss_metrics as rss

# Import the AST classes
from mylab.envs.ast_env import ASTEnv
from mylab.samplers.ast_vectorized_sampler import ASTVectorizedSampler

# Import the necessary garage classes
from garage.tf.algos.trpo import TRPO
from garage.tf.envs.base import TfEnv
from garage.tf.policies.gaussian_lstm_policy import GaussianLSTMPolicy
from garage.tf.optimizers.conjugate_gradient_optimizer import ConjugateGradientOptimizer, FiniteDifferenceHvp
from garage.baselines.linear_feature_baseline import LinearFeatureBaseline
from garage.envs.normalized_env import normalize
from garage.misc import logger

# Useful imports
import os.path as osp
import argparse
from example_save_trials import *
import tensorflow as tf
import numpy as np
import pdb

import faulthandler
faulthandler.enable()


# Logger Params
parser = argparse.ArgumentParser()
parser.add_argument('--exp_name', type=str, default='crosswalk_exp')
parser.add_argument('--tabular_log_file', type=str, default='tab.txt')
parser.add_argument('--text_log_file', type=str, default='tex.txt')
parser.add_argument('--params_log_file', type=str, default='args.txt')
parser.add_argument('--snapshot_mode', type=str, default="gap")
parser.add_argument('--snapshot_gap', type=int, default=10)
parser.add_argument('--log_tabular_only', type=bool, default=False)
parser.add_argument('--log_dir', type=str, default='.')
parser.add_argument('--args_data', type=str, default=None)
args = parser.parse_args()

# Create the logger
log_dir = args.log_dir

tabular_log_file = osp.join(log_dir, args.tabular_log_file)
text_log_file = osp.join(log_dir, args.text_log_file)
params_log_file = osp.join(log_dir, args.params_log_file)

logger.log_parameters_lite(params_log_file, args)
logger.add_text_output(text_log_file)
logger.add_tabular_output(tabular_log_file)
prev_snapshot_dir = logger.get_snapshot_dir()
prev_mode = logger.get_snapshot_mode()
logger.set_snapshot_dir(log_dir)
logger.set_snapshot_mode(args.snapshot_mode)
logger.set_snapshot_gap(args.snapshot_gap)
logger.set_log_tabular_only(args.log_tabular_only)
logger.push_prefix("[%s] " % args.exp_name)

# Instantiate the example classes

# Define the longitudinal and lateral params for rss
g = 9.8 # acceleration due to gravity

# this is y
lat_params = rss.LateralParams( 0, #ρ
                            0.1*g, # a_lat_max_acc
                            0.05*g, # a_lat_min_brake
                            1.4 # Buffer distance
                            )

# this is x
long_params = rss.LongitudinalParams(   0, #ρ
                                    0.7*g, #a_max_brake
                                    0.1*g, # a_max_acc
                                    0.7*g, # a_min_brake1
                                    0.7*g, # a_min_brake2
                                    2.5, # Buffer
                                    )


sim = AVRSSSimulator(lat_params, long_params)
reward_function = HeuristicReward(PedestrianNoiseGaussian(1, 1, 0.2, .01), np.array([-10000, -1000]))
spaces = ExampleAVSpaces()

# Create the environment
env = TfEnv(normalize(ASTEnv(action_only=True,
                             fixed_init_state=True,
                             s_0=[-0.0, -4.0, 1.0, 11.17, -35.0],
                             simulator=sim,
                             reward_function=reward_function,
                             spaces=spaces
                             )))

# Instantiate the garage objects
policy = GaussianLSTMPolicy(name='lstm_policy',
                            env_spec=env.spec,
                            hidden_dim=64,
                            use_peepholes=True)
baseline = LinearFeatureBaseline(env_spec=env.spec)
sampler_cls = ASTVectorizedSampler
optimizer = ConjugateGradientOptimizer
optimizer_args = {'hvp_approach':FiniteDifferenceHvp(base_eps=1e-5)}
algo = TRPO(
    env=env,
    policy=policy,
    baseline=LinearFeatureBaseline(env_spec=env.spec),
    batch_size=50000,
    step_size=0.1,
    n_itr=101,
    store_paths=True,
    optimizer=optimizer,
    optimizer_args=optimizer_args,
    max_path_length=50,
    sampler_cls=sampler_cls,
    sampler_args={"sim": sim,
                  "reward_function": reward_function})


with tf.Session() as sess:
    # Run the experiment
    algo.train(sess=sess)

    # Write out the episode results
    header = 'trial, step, ' + 'v_x_car, v_y_car, x_car, y_car, '
    for i in range(0,sim.c_num_peds):
        header += 'v_x_ped_' + str(i) + ','
        header += 'v_y_ped_' + str(i) + ','
        header += 'x_ped_' + str(i) + ','
        header += 'y_ped_' + str(i) + ','

    for i in range(0,sim.c_num_peds):
        header += 'a_x_'  + str(i) + ','
        header += 'a_y_' + str(i) + ','
        header += 'noise_v_x_' + str(i) + ','
        header += 'noise_v_y_' + str(i) + ','
        header += 'noise_x_' + str(i) + ','
        header += 'noise_y_' + str(i) + ','

    header += 'reward'
    example_save_trials(algo.n_itr, args.log_dir, header, sess, save_every_n=args.snapshot_gap)

