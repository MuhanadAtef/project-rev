import json
import numpy as np
import random
from python_speech_features import mfcc
import scipy.io.wavfile as wav
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable

from utils import calc_feat_dim, spectrogram_from_file, text_to_int_sequence

RNG_SEED = 123


class AudioGenerator:
    def __init__(self, step=10, window=20, max_freq=8000, mfcc_dim=13,
                 minimum_batch_size=20, desc_file=None, spectrogram=True, max_duration=10.0,
                 sort_by_duration=False):
        """ Generates training, validation and testing data
            :param step: (int) Step size in milliseconds between windows (for spectrogram ONLY)
            :param window: (int) FFT window size in milliseconds (for spectrogram ONLY)
            :param max_freq: (int) Only FFT bins corresponding to frequencies between
                [0, max_freq] are returned (for spectrogram ONLY)
            :param desc_file: (str, optional) Path to a JSON-line file that contains
                labels and paths to the audio files. If this is None, then
                load metadata right away
        """

        self.feat_dim = calc_feat_dim(window, max_freq)
        self.mfcc_dim = mfcc_dim
        self.feats_mean = np.zeros((self.feat_dim,))
        self.feats_std = np.ones((self.feat_dim,))
        self.rng = random.Random(RNG_SEED)
        if desc_file is not None:
            self.load_metadata_from_desc_file(desc_file)
        self.step = step
        self.window = window
        self.max_freq = max_freq
        self.cur_train_index = 0
        self.cur_valid_index = 0
        self.cur_test_index = 0
        self.max_duration = max_duration
        self.minimum_batch_size = minimum_batch_size
        self.spectrogram = spectrogram
        self.sort_by_duration = sort_by_duration

    def get_batch(self, partition):
        """ Obtain a batch of train, validation, or test data
            :param partition: (string) Chooses from ('train', 'valid', 'test')
            :raises: Exception if partition has a value different from ('train', 'valid', 'test')
            :returns inputs: Contains the wav audio, label, input length and label length
        """
        if partition == 'train':
            audio_paths = self.train_audio_paths
            cur_index = self.cur_train_index
            texts = self.train_texts
        elif partition == 'valid':
            audio_paths = self.valid_audio_paths
            cur_index = self.cur_valid_index
            texts = self.valid_texts
        elif partition == 'test':
            audio_paths = self.test_audio_paths
            cur_index = self.test_valid_index
            texts = self.test_texts
        else:
            raise Exception("Invalid partition. "
                            "Must be train/validation or test")

        features = [self.normalize(self.featurize(a)) for a in
                    audio_paths[cur_index:cur_index + self.minimum_batch_size]]

        # Calculate necessary sizes
        max_length = max([features[i].shape[0]
                          for i in range(0, self.minimum_batch_size)])
        max_string_length = max([len(texts[cur_index + i])
                                 for i in range(0, self.minimum_batch_size)])

        # Initialize the arrays
        input_data = np.zeros([self.minimum_batch_size, max_length,
                               self.feat_dim * self.spectrogram + self.mfcc_dim * (not self.spectrogram)])
        labels = np.ones([self.minimum_batch_size, max_string_length]) * 28  # Set all labels as blank
        input_length = np.zeros([self.minimum_batch_size, 1])
        label_length = np.zeros([self.minimum_batch_size, 1])

        for i in range(0, self.minimum_batch_size):
            # Calculate input_data & input_length
            feat = features[i]
            input_length[i] = feat.shape[0]
            input_data[i, :feat.shape[0], :] = feat

            # Calculate labels & label_length
            label = np.array(text_to_int_sequence(texts[cur_index + i]))
            labels[i, :len(label)] = label
            label_length[i] = len(label)

        # Return the arrays
        outputs = {'ctc': np.zeros([self.minimum_batch_size])}
        inputs = {'the_input': input_data,
                  'the_labels': labels,
                  'input_length': input_length,
                  'label_length': label_length
                  }
        return inputs, outputs

    def featurize(self, audio_clip):
        """ For a given audio clip, calculate the corresponding feature
            :param: audio_clip: (str) Path to the audio clip
            :returns: Spectrogram or MFCC
        """
        if self.spectrogram:
            return spectrogram_from_file(
                audio_clip, step=self.step, window=self.window,
                max_freq=self.max_freq)
        else:
            (rate, sig) = wav.read(audio_clip)
            return mfcc(sig, rate, numcep=self.mfcc_dim)

    def normalize(self, feature, eps=1e-14):
        """ Center a feature using the mean and std
            :param: feature: (numpy.ndarray) Feature to normalize
            :returns: The normalized features
        """
        return (feature - self.feats_mean) / (self.feats_std + eps)

    def shuffle_data_by_partition(self, partition):
        """ Shuffle the training or validation data
        :param: partition: (str) train or valid
        :raises: Exception if the partition was not train/valid
        :returns: Shuffled validation or training datasets
        """
        if partition == 'train':
            self.train_audio_paths, self.train_durations, self.train_texts = shuffle_data(
                self.train_audio_paths, self.train_durations, self.train_texts)
        elif partition == 'valid':
            self.valid_audio_paths, self.valid_durations, self.valid_texts = shuffle_data(
                self.valid_audio_paths, self.valid_durations, self.valid_texts)
        else:
            raise Exception("Invalid partition. "
                            "Must be train/validation")


def shuffle_data(audio_paths, durations, texts):
    """ Shuffle the data (called after making a complete pass through
        training or validation data during the training process)
        :param: audio_paths: (list) Paths to audio clips
        :param: durations: (list) Durations of utterances for each audio clip
        :param: texts: (list) Sentences uttered in each audio clip
        :returns: Shuffled data with paths, duration and texts
    """
    p = np.random.permutation(len(audio_paths))
    audio_paths = [audio_paths[i] for i in p]
    durations = [durations[i] for i in p]
    texts = [texts[i] for i in p]
    return audio_paths, durations, texts


def sort_data(audio_paths, durations, texts):
    """ Sort the data by duration
        :param: audio_paths: (list) Paths to audio clips
        :param: durations: (list) Durations of utterances for each audio clip
        :param: texts: (list) Sentences uttered in each audio clip
        :returns: Sorted data with paths, duration and texts
    """
    p = np.argsort(durations).tolist()
    audio_paths = [audio_paths[i] for i in p]
    durations = [durations[i] for i in p]
    texts = [texts[i] for i in p]
    return audio_paths, durations, texts
