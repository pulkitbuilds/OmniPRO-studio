import os
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset
from torchvision.models import vgg19, VGG19_Weights
from model import VideoSuperResolutionNet


class PerceptualLoss(nn.Module):
    """VGG19 Feature Reconstruction Loss for realistic high-frequency detail."""

    def __init__(self):
        super().__init__()
        vgg = vgg19(weights=VGG19_Weights.DEFAULT)
        self.feature_extractor = nn.Sequential(
            *list(vgg.features.children())[:35]
        ).eval()
        for param in self.feature_extractor.parameters():
            param.requires_grad = False

    def forward(self, hr_pred: torch.Tensor, hr_target: torch.Tensor) -> torch.Tensor:
        return nn.functional.l1_loss(
            self.feature_extractor(hr_pred), self.feature_extractor(hr_target)
        )


class VideoFrameDataset(Dataset):
    """Loads paired Low-Resolution (LR) and High-Resolution (HR) frame crops."""

    def __init__(self, lr_dir: str, hr_dir: str, transform=None):
        self.lr_files = sorted([os.path.join(lr_dir, f) for f in os.listdir(lr_dir)])
        self.hr_files = sorted([os.path.join(hr_dir, f) for f in os.listdir(hr_dir)])
        self.transform = transform

    def __len__(self) -> int:
        return len(self.lr_files)

    def __getitem__(self, idx: int):
        raise NotImplementedError("Implement custom frame loader here")


def train_model(
    train_loader,
    epochs: int = 50,
    lr: float = 1e-4,
    scale: int = 4,
    save_path: str = "models/video_enhancer_model.pth",
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = VideoSuperResolutionNet(scale=scale).to(device)

    criterion_l1 = nn.L1Loss()
    criterion_perceptual = PerceptualLoss().to(device)
    optimizer = optim.Adam(model.parameters(), lr=lr, betas=(0.9, 0.999))

    print(f"Training on device: {device}")
    model.train()
    for epoch in range(epochs):
        epoch_loss = 0.0
        for lr_batch, hr_batch in train_loader:
            lr_batch = lr_batch.to(device)
            hr_batch = hr_batch.to(device)

            optimizer.zero_grad()
            pred_hr = model(lr_batch)

            l1_loss = criterion_l1(pred_hr, hr_batch)
            perc_loss = criterion_perceptual(pred_hr, hr_batch)
            total_loss = l1_loss + 0.1 * perc_loss

            total_loss.backward()
            optimizer.step()
            epoch_loss += total_loss.item()

        print(f"Epoch [{epoch+1}/{epochs}] Loss: {epoch_loss / len(train_loader):.4f}")
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        torch.save(model.state_dict(), save_path)

    print(f"Model saved to {save_path}")
