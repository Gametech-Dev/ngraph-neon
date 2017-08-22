from __future__ import print_function
import logging
from collections import deque

import numpy as np
from ngraph.frontends.neon.logging import ProgressBar, PBStreamHandler

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(PBStreamHandler(level=logging.INFO))


def rl_loop_train(environment, agent, episodes, render=False):
    """
    train an agent inside an environment for a set number of episodes

    This function should be common to all reinforcement learning algorithms.
    New algorithms should be written by implementing the Agent interface. An
    example of agent implementing such an interface can be found in dqn.py.
    """
    total_steps = 0
    rewards = deque(maxlen=500)
    progress_bar = ProgressBar(unit="episodes", ncols=100, total=episodes)
    for episode in progress_bar(iter(range(episodes))):
        state = environment.reset()
        done = False
        step = 0
        total_reward = 0
        trigger_evaluation = False
        while not done:
            if render:
                environment.render()

            action = agent.act(state)
            next_state, reward, done, _ = environment.step(action)
            agent.observe_results(
                state, action, reward, next_state, done, total_steps
            )

            state = next_state
            step += 1
            total_steps += 1
            total_reward += reward

            if total_steps % 50000 == 0:
                trigger_evaluation = True

        agent.end_of_episode()
        rewards.append(total_reward)
        progress_bar.set_description("Average Reward {:0.4f}".format(np.mean(rewards)))
        # we would like to evaluate the model at a consistent time measured
        # in update steps, but we can't start an evaluation in the middle of an
        # episode.  if we have accumulated enough updates to warrant an evaluation
        # set trigger_evaluation to true, and run an evaluation at the end of
        # the episode.
        if trigger_evaluation:
            trigger_evaluation = False

            logger.info({
                'type': 'training episode',
                'episode': episode,
                'total_steps': total_steps,
                'steps': step,
                'total_reward': total_reward,
                'running_average_reward': np.mean(rewards),
            })

            for epsilon in (0, 0.01, 0.05, 0.1):
                total_reward = evaluate_single_episode(
                    environment, agent, render, epsilon
                )

                logger.info({
                    'type': 'evaluation episode',
                    'epsilon': epsilon,
                    'total_steps': total_steps,
                    'total_reward': total_reward,
                })


def evaluate_single_episode(environment, agent, render=False, epsilon=None):
    """
    Evaluate a single episode of agent operating inside of an environment.

    This method should be applicable to all reinforcement learning algorithms
    so long as they implement the Agent interface.
    """
    state = environment.reset()
    done = False
    step = 0
    total_reward = 0
    while not done:
        if render:
            environment.render()

        action = agent.act(state, training=False, epsilon=epsilon)
        next_state, reward, done, _ = environment.step(action)

        state = next_state
        step += 1
        total_reward += reward

    agent.end_of_episode()

    return total_reward
