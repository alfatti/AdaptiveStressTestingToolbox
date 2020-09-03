import argparse
import csv
import math
import os
import os.path as osp

import joblib
import numpy as np
import src.ast_toolbox.mcts.BoundedPriorityQueues as BPQ
# from example_save_trials import *
import tensorflow as tf
from CartPole.cartpole_simulator import CartpoleSimulator
# from garage.tf.algos.trpo import TRPO
from garage.baselines.linear_feature_baseline import LinearFeatureBaseline
from garage.misc import logger
from garage.tf.optimizers.conjugate_gradient_optimizer import ConjugateGradientOptimizer
from garage.tf.optimizers.conjugate_gradient_optimizer import FiniteDifferenceHvp
from garage.tf.policies.gaussian_lstm_policy import GaussianLSTMPolicy
from src.ast_toolbox import TRPO
from src.ast_toolbox import ASTEnv
from src.ast_toolbox import TfEnv
from src.ast_toolbox.rewards import ASTRewardS

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # just use CPU


# Logger Params
parser = argparse.ArgumentParser()
parser.add_argument('--exp_name', type=str, default='cartpole')
parser.add_argument('--nd', type=int, default=1)
parser.add_argument('--sut_itr', type=int, default=5)
parser.add_argument('--n_trial', type=int, default=10)
parser.add_argument('--trial_start', type=int, default=0)
parser.add_argument('--n_itr', type=int, default=1000)
parser.add_argument('--step_size', type=float, default=0.1)
parser.add_argument('--batch_size', type=int, default=2000)  # 50000
parser.add_argument('--snapshot_mode', type=str, default="none")
parser.add_argument('--snapshot_gap', type=int, default=500)
parser.add_argument('--log_dir', type=str, default='./Data/AST/TRPOLSTM')
parser.add_argument('--args_data', type=str, default=None)
args = parser.parse_args()
args.log_dir += ('B' + str(args.batch_size) + 'Step' + str(args.step_size))

top_k = 10
max_path_length = 100
open_loop = True

tf.set_random_seed(0)
sess = tf.Session()
sess.__enter__()

# Instantiate the env
data = joblib.load("../CartPole/ControlPolicy/itr_" + str(args.sut_itr) + ".pkl")
sut = data['policy']
reward_function = ASTRewardS()

simulator = CartpoleSimulator(sut=sut, max_path_length=100, use_seed=False, nd=args.nd)
env = TfEnv(ASTEnv(open_loop=open_loop,
                   simulator=simulator,
                   fixed_init_state=True,
                   s_0=[0.0, 0.0, 0.0 * math.pi / 180, 0.0],
                   reward_function=reward_function,
                   ))

# Create policy
policy = GaussianLSTMPolicy(name='lstm_policy',
                            env_spec=env.spec,
                            hidden_dim=64,
                            use_peepholes=True)

with open(osp.join(args.log_dir, 'total_result.csv'), mode='w') as csv_file:
    fieldnames = ['step_count']
    for i in range(top_k):
        fieldnames.append('reward ' + str(i))
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()

    for trial in range(args.trial_start, args.trial_start + args.n_trial):
        # Create the logger
        log_dir = args.log_dir + '/' + str(trial)

        tabular_log_file = osp.join(log_dir, 'process.csv')
        text_log_file = osp.join(log_dir, 'text.txt')
        params_log_file = osp.join(log_dir, 'args.txt')

        logger.set_snapshot_dir(log_dir)
        logger.set_snapshot_mode(args.snapshot_mode)
        logger.set_snapshot_gap(args.snapshot_gap)
        logger.log_parameters_lite(params_log_file, args)
        if trial > args.trial_start:
            old_log_dir = args.log_dir + '/' + str(trial - 1)
            logger.pop_prefix()
            logger.remove_text_output(osp.join(old_log_dir, 'text.txt'))
            logger.remove_tabular_output(osp.join(old_log_dir, 'process.csv'))
        logger.add_text_output(text_log_file)
        logger.add_tabular_output(tabular_log_file)
        logger.push_prefix("[" + args.exp_name + '_trial ' + str(trial) + "]")

        np.random.seed(trial)

        params = policy.get_params()
        sess.run(tf.variables_initializer(params))
        baseline = LinearFeatureBaseline(env_spec=env.spec)
        optimizer = ConjugateGradientOptimizer
        optimizer_args = {'hvp_approach': FiniteDifferenceHvp(base_eps=1e-5)}

        top_paths = BPQ.BoundedPriorityQueue(top_k)
        algo = TRPO(
            env=env,
            policy=policy,
            baseline=baseline,
            batch_size=args.batch_size,
            step_size=args.step_size,
            n_itr=args.n_itr,
            store_paths=True,
            optimizer=optimizer,
            optimizer_args=optimizer_args,
            max_path_length=max_path_length,
            top_paths=top_paths,
            plot=False,
        )

        algo.train(sess=sess, init_var=False)

        row_content = dict()
        row_content['step_count'] = args.n_itr * args.batch_size
        i = 0
        for (r, action_seq) in algo.top_paths:
            row_content['reward ' + str(i)] = r
            i += 1
        writer.writerow(row_content)