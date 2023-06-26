import torch
import os
import sys
import torch.nn.functional as F
import numpy as np
from TAP_estimator import AcousticEstimator
from typing import *

class AcousticLoss(torch.nn.Module):
    def __init__(self, loss_type: str, acoustic_model_path: str, device = 'cuda'):
        """
        Args:
            loss_type (str):
                Must be one of the following 4 options: ["l2", "l1", "frame_energy_weighted_l2", "frame_energy_weighted_l1"]
            acoustic_model_path (str):
                Path to the pretrained temporal acoustic parameter estimator model checkpoint.
        """
        super(AcousticLoss, self).__init__()
        self.device       = device
        self.estimate_acoustics = AcousticEstimator()
        self.loss_type = loss_type
        if self.loss_type == "l2":
            self.l2 = torch.nn.MSELoss()
        elif self.loss_type == "l1":
            self.l1 = torch.nn.L1Loss()    
        
        model_state_dict  = torch.load(acoustic_model_path, map_location=device)['model_state_dict']
        self.estimate_acoustics.load_state_dict(model_state_dict)
        self.estimate_acoustics.to(device)
        
    def __call__(self, clean_waveform, enhan_waveform, mode="train"):
        return self.forward(clean_waveform, enhan_waveform, mode)

    def forward(self, clean_waveform: torch.FloatTensor, enhan_waveform: torch.FloatTensor, mode: str) -> torch.FloatTensor:

        """
        Args:
            clean_waveform (torch.FloatTensor)：
                Tensor of clean waveform with shape (B, T * sr).
            enhan_waveform (torch.FloatTensor)： 
                Tensor of enhanced waveform with shape (B, T * sr).
            mode (str) : 
                'train' or 'eval'
        Returns:
            acoustic_loss (torch.FloatTensor):
                Loss value corresponding to the selected loss type.
        """
        
        if   mode == "train":
            self.estimate_acoustics.train()
        elif mode == "eval":
            self.estimate_acoustics.eval()     
        else:
            raise ValueError("Invalid mode, must be either 'train' or 'eval'.")
            
            
        clean_spectrogram = self.get_stft(clean_waveform)
        enhan_spectrogram, enhan_st_energy = self.get_stft(enhan_waveform, return_short_time_energy = True)
        clean_acoustics   = self.estimate_acoustics(clean_spectrogram)
        enhan_acoustics   = self.estimate_acoustics(enhan_spectrogram)

        """
        loss_type must be one of the following 4 options:
        ["l2", "l1", "frame_energy_weighted_l2", "frame_energy_weighted_l1"]
        """
        if self.loss_type == "l2":
            acoustic_loss   = self.l2(enhan_acoustics, clean_acoustics)
        elif self.loss_type == "l1":
            acoustic_loss   = self.l1(enhan_acoustics, clean_acoustics)
        elif self.loss_type == "frame_energy_weighted_l2":
            acoustic_loss   = torch.mean(((torch.sigmoid(enhan_st_energy)** 0.5).unsqueeze(dim = -1) \
            * (enhan_acoustics - clean_acoustics)) ** 2 )                                       
        elif self.loss_type == "frame_energy_weighted_l1":
            acoustic_loss   = torch.mean(torch.sigmoid(enhan_st_energy).unsqueeze(dim = -1) \
            * torch.abs(enhan_acoustics - clean_acoustics))
        else:
            raise ValueError("Invalid loss_type {}".format(self.loss_type))
    
        return acoustic_loss            
           
    
    def get_stft(self, wav: torch.FloatTensor, return_short_time_energy: bool = False) -> torch.FloatTensor:
        """
        Args:
            wav (torch.FloatTensor):
                Tensor of waveform of shape: (B, T * sr).
            return_short_time_energy (bool):
                True to return both complex spectrogram and short-time energy.
        Returns:
            spec (torch.FloatTensor): 
                Real value representation of complex spectrograms, real part \
                and imag part alternate along the frequency axis. 
            st_energy (torch.FloatTensor):
                Short-time energy calculated in the frequency domain using Parseval's theorem.  
        """
        self.nfft       = 512
        self.hop_length = 160
        spec = torch.stft(wav, n_fft=self.nfft, hop_length=self.hop_length, return_complex=False) # Rectangular window with window length = 32ms, hop length = 10ms
        spec_real = spec[..., 0]
        spec_imag = spec[..., 1]     
        spec = spec.permute(0, 2, 1, 3).reshape(spec.size(dim=0), -1,  2 * (self.nfft//2 + 1)) # spec ==> (B, T * sr, 2 * (nfft / 2 + 1))

        if return_short_time_energy:
            st_energy = torch.mul(torch.sum(spec_real**2 + spec_imag**2, dim = 1), 2/self.nfft) 
            return spec.float(), st_energy.float()
        else: 
            return spec.float()
        
        


