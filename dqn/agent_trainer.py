"""
Script Name: agent_trainer.py

Deep Q-Network (DQN) implementation for playing Atari games.
This script trains a neural network to learn how to play the game
using reinforcement learning and saves the trained policy network.
"""
from collections import deque
from tqdm import tqdm
import torch
import torch.optim as optim
import torch.nn.functional as f
from atari_wrappers import wrap_deepmind, make_atari
import dqn as model
import os

pretrained_policy_path = "./trained_policies/trained_policy_network.pt"
new_policy_path="./trained_policies/new_policy_network.pt"

batch_size = 32                          # Number of experiences to sample from the replay buffer for each training iteration
gamma = 0.99                             # Discount factor used in the Q-learning update equation
initial_epsilon = 0.05                   # Initial value of the exploration rate for epsilon-greedy action selection strategy
final_epsilon = 0.05                     # Final value of the exploration rate for epsilon-greedy action selection strategy
epsilon_decay = 20000                    # Number of steps over which to decay the exploration rate from initial to final value
optimizer_epsilon = 1.5e-4               # Learning rate for the optimizer used to update the policy network
adam_learning_rate = 0.0000625           # Learning rate for the Adam optimizer used to update the target network
target_network_update = 10000            # Frequency (in steps) at which to update the target network
STEP = 4000000                           # Total number of STEP to train for
memory_size = 1000000                    # Maximum size of the replay buffer
policy_network_update = 4                # Frequency (in steps) at which to update the policy network
policy_saving_frequency = 4              # Frequency (in STEP) at which to save the policy network
num_eval_episode = 15                    # Number of STEP to evaluate the policy network on during evaluation
random_exploration_interval = 10000      # Number of steps during which to perform random exploration before using the policy network
evaluation_frequency = 25000             # Frequency (in steps) at which to evaluate the policy network
max_episode_steps = 400000               # Maximum number of steps to take in each episode
frame_stack_size = 5                     # Number of frames to stack together to form an input to the neural network
previous_experience = 100000             # Number of experiences to collect in the replay buffer before starting training


# This function evaluates a PyTorch neural network model on a wrapped OpenAI gym environment
def evaluate(step, policy_net, device, env, n_actions, train,episode):
    # Wrap the OpenAI gym environment in a deepmind wrapper
    env = wrap_deepmind(env)

    # Initialize an action selector using hyperparameters and the input policy network
    action_selector = model.ActionSelector(initial_epsilon, final_epsilon, epsilon_decay, random_exploration_interval,
                                         policy_net, n_actions, device)

    # Initialize an empty list to store the total rewards obtained in each episode
    total_rewards = []

    # Initialize a deque to store a sequence of frames (used for state representation)
    frame_stack = deque(maxlen=frame_stack_size)

    # Run a fixed number of evaluation STEP on the environment
    for i in range(num_eval_episode):

        # Reset the environment and initialize the episode reward
        env.reset()
        episode_reward = 0

        # Initialize the frame stack with a sequence of initial frames
        for _ in range(10):
            pixels, _, done, _ = env.step(0)
            pixels = model.get_frame_tensor(pixels)
            frame_stack.append(pixels)

        # Loop until the end of the episode is reached
        while not done:
            # Concatenate the current frame stack to create the current state representation
            state_tensor = torch.cat(list(frame_stack))[1:].unsqueeze(0)

            # Select an action using the action selector
            action, eps = action_selector.select_action(state_tensor, step, train)

            # Take a step in the environment with the selected action and update the frame stack
            pixels, reward, done, info = env.step(action)
            pixels = model.get_frame_tensor(pixels)
            frame_stack.append(pixels)

            # Update the episode reward
            episode_reward += reward

        # Store the episode reward in the total_rewards list
        total_rewards.append(episode_reward)
    print("episode : {0} , score : {1:.1f}".format(episode,(float(sum(total_rewards)) / float(num_eval_episode))))
    # Write the average episode reward, current step, and current epsilon to a score record file
    output_file = open("./score_record.txt", 'a')
    output_file.write("%f, %d, %f \n" % (float(sum(total_rewards)) / float(num_eval_episode), step, eps))
    output_file.close()


# This function takes in a PyTorch model as input
def load_pretrained_model(model):
    # Check if a pre-trained model exists at the specified path
    if os.path.isfile(pretrained_policy_path):
        # If a pre-trained model exists, load its state dictionary into the input model
        print("Loading pre-trained model from", pretrained_policy_path)
        model.load_state_dict(torch.load(pretrained_policy_path))
    elif os.path.isfile(new_policy_path):
        # If a pre-trained model exists, load its state dictionary into the input model
        print("Loading pre-trained model from", new_policy_path,"(start from last training)")
        model.load_state_dict(torch.load(new_policy_path))
    else:
        # If a pre-trained model does not exist, initialize the input model's weights from scratch
        print("Pre-trained model not found. Training from scratch.")
        model.apply(model.init_weights)
    # Return the input model (either loaded with a pre-trained model or initialized from scratch)
    return model


# This function optimizes a PyTorch neural network model using a batch of experiences
def optimize_model(train, optimizer, memory, policy_net, target_net):
    # If the train flag is False, return from the function without optimizing the model
    if not train:
        return

    # Sample a batch of experiences from memory
    state_batch, action_batch, reward_batch, n_state_batch, done_batch = memory.sample(batch_size)
    # Compute the Q-values for the current state and action using the policy network
    q_network = policy_net(state_batch).gather(1, action_batch)
    # Compute the maximum Q-value for the next state using the target network
    t_network = target_net(n_state_batch).max(1)[0].detach()
    # Compute the expected Q-value for the current state and action using the Bellman equation
    expected_state_action_values = (t_network * gamma) * (1. - done_batch[:, 0]) + reward_batch[:, 0]
    # Compute the loss between the Q-values predicted by the policy network and the expected Q-values
    loss = f.smooth_l1_loss(q_network, expected_state_action_values.unsqueeze(1))
    # Zero out the gradients of the optimizer
    optimizer.zero_grad()
    # Backpropagate the loss through the model
    loss.backward()
    # Clip the gradients to be between -1 and 1
    for param in policy_net.parameters():
        param.grad.data.clamp_(-1, 1)
    # Update the parameters of the model using the optimizer
    optimizer.step()

def main():
    # Set the CUDA_VISIBLE_DEVICES environment variable to use GPU if available
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    # Set the device to CUDA if available, else CPU
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # Set the name of the game environment
    env_name = 'Breakout'
    # Create a raw Atari environment without frame skipping
    env_raw = make_atari('{}NoFrameskip-v4'.format(env_name), max_episode_steps, False)

    # Wrap the Atari environment in a DeepMind wrapper
    env = wrap_deepmind(env_raw, frame_stack=False, episode_life=True, clip_rewards=True)


    # Get the replay buffer capacity, height, and width from the first frame
    replay_buffer_capacity, height, width = model.get_frame_tensor(env.reset()).shape

    # Get the number of possible actions in the game
    possible_actions = env.action_space.n

    # Initialize the policy and target networks using the DQN class
    policy_network = model.DQN(possible_actions, device).to(device)
    target_network = model.DQN(possible_actions, device).to(device)

    # Load the pre-trained policy network, and synchronize the target network with it
    policy_network=load_pretrained_model(policy_network)
    target_network.load_state_dict(policy_network.state_dict())
    target_network.eval()

    # Initialize the optimizer using the Adam algorithm
    optimizer = optim.Adam(policy_network.parameters(), lr=adam_learning_rate, eps=optimizer_epsilon)

    # Initialize the replay memory buffer
    memory = model.ReplayMemory(memory_size, [frame_stack_size, height, width], device)

    # Initialize the action selector
    action_selector = model.ActionSelector(initial_epsilon, final_epsilon, epsilon_decay, random_exploration_interval, policy_network, possible_actions, device)

    # Initialize the frame stack and episode length
    frame_stack = deque(maxlen=frame_stack_size)
    done = True
    episode_len = 0

    # Initialize the progress bar for training STEP
    training_progress_bar = tqdm(range(STEP), total=STEP, ncols=50, leave=False, unit='b')

    episode = 0

    # Loop over the training STEP
    for step in training_progress_bar:

        # Reset the environment if the episode is done, and initialize the frame stack and episode length
        if done:
            episode += 1
            env.reset()
            episode_len = 0

            for i in range(10):
                pixels, _, _, _ = env.step(0)
                pixels = model.get_frame_tensor(pixels)
                frame_stack.append(pixels)

        # Determine whether the agent is currently training or exploring randomly
        training_flag = len(memory) > max(random_exploration_interval-previous_experience,0)

        # Create the current state representation using the frame stack
        state = torch.cat(list(frame_stack))[1:].unsqueeze(0)

        # Select an action using the action selector, and take the action in the environment
        action, eps = action_selector.select_action(state, step+previous_experience, training_flag)
        pixels, reward, done, info = env.step(action)
        pixels = model.get_frame_tensor(pixels)
        frame_stack.append(pixels)

        # Add the current state, action, reward, and done flag to the replay memory buffer
        memory.push(torch.cat(list(frame_stack)).unsqueeze(0), action, reward, done)
        episode_len += 1

        # Evaluate the performance of the policy network periodically
        if step % evaluation_frequency == 0:
            evaluate(step + previous_experience, policy_network, device, env_raw, possible_actions, training_flag,episode)

        # Optimize the policy network periodically
        if step % policy_network_update == 0:
            optimize_model(training_flag, optimizer, memory, policy_network, target_network)

        # Synchronize the target network with the policy network periodically
        if step % target_network_update == 0:
            target_network.load_state_dict(policy_network.state_dict())

        # Save the policy network weights periodically
        if step % policy_saving_frequency == 0:
            torch.save(policy_network.state_dict(), new_policy_path)


if __name__ == '__main__':
    main()