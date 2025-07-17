# 文件：configs/custom/mask_rcnn_goods_pallet_floor.py


_base_ = [
    '../configs/mask-rcnn_r50_fpn.py'
]

# 1. 数据集配置
dataset_type = 'CocoDataset'
data_root = 'datasets/'

classes = ('cargo', 'pallet', 'floor')

train_pipeline = [
    dict(type='LoadImageFromFile'),
    dict(type='LoadAnnotations', with_bbox=True, with_mask=True),
    dict(type='Resize', scale=(1333, 800), keep_ratio=True),  # 统一大小
    dict(type='RandomFlip', prob=0.5),
    dict(type='Pad', size_divisor=32),  # 自动补齐使尺寸可被32整除
    dict(type='PackDetInputs')
]


train_dataloader = dict(
    batch_size=1,
    #num_workers=1,
    persistent_workers=False,
    sampler=dict(type='DefaultSampler', shuffle=True),
    batch_sampler=dict(type='AspectRatioBatchSampler'),
    dataset=dict(
        type=dataset_type,
        ann_file= 'train/annotations.json',
        data_root=data_root,
        data_prefix=dict(img='train/images/'),  # 新版本写法，替代 img_prefix
        pipeline=train_pipeline,
        metainfo=dict(classes=classes),
        filter_cfg=dict(filter_empty_gt=True),
    )
)

val_dataloader = dict(
    batch_size=1,
    #num_workers=1,
    persistent_workers=False,
    sampler=dict(type='DefaultSampler', shuffle=False),
    batch_sampler=dict(type='AspectRatioBatchSampler'),
    dataset=dict(
        type=dataset_type,
        ann_file= 'val/annotations.json',
        data_root=data_root,
        data_prefix=dict(img='val/images/'),  # 替代 img_prefix
        metainfo=dict(classes=classes),
        pipeline=[
            dict(type='LoadImageFromFile'),
            dict(type='Resize', scale=(1333, 800), keep_ratio=True),
            dict(type='RandomFlip', prob=0.0),  # 添加这行，即使不做翻转也能生成 flip 字段
            dict(type='LoadAnnotations', with_bbox=True, with_mask=True),
            dict(type='PackDetInputs')  # <== 必须要有
        ]
    )
)

test_dataloader = val_dataloader

val_evaluator = dict(
    type='CocoMetric',
    ann_file=data_root + 'val/annotations.json',
    metric=['bbox', 'segm']
)

test_evaluator = val_evaluator

# 2. 模型配置（改类别数）
model = dict(
    roi_head=dict(
        bbox_head=dict(num_classes=3),
        mask_head=dict(num_classes=3)
    )
)

# 3. 优化器和学习率调度
optim_wrapper = dict(
    type='OptimWrapper',
    optimizer=dict(type='SGD', lr=0.02, momentum=0.9, weight_decay=0.0001)
)

param_scheduler = [
    dict(type='LinearLR', start_factor=0.001, by_epoch=False, begin=0, end=500),
    dict(type='MultiStepLR', by_epoch=True, milestones=[8, 11], gamma=0.1)
]

# 4. 训练相关配置
train_cfg = dict(type='EpochBasedTrainLoop', max_epochs=20, val_interval=1)
val_cfg = dict(type='ValLoop')
test_cfg = dict(type='TestLoop')

# 5. 默认 hooks（不要加 evaluation 或 visualization）
default_hooks = dict(
    timer=dict(type='IterTimerHook'),
    logger=dict(type='LoggerHook', interval=50),
    param_scheduler=dict(type='ParamSchedulerHook'),
    checkpoint=dict(type='CheckpointHook', interval=1),
    sampler_seed=dict(type='DistSamplerSeedHook')
)

# 6. 环境 & 日志设置
env_cfg = dict(
    cudnn_benchmark=False,
    mp_cfg=dict(mp_start_method='fork', opencv_num_threads=0),
    dist_cfg=dict(backend='nccl')
)

log_processor = dict(type='LogProcessor', window_size=50, by_epoch=True)
log_level = 'INFO'

# 7. 预训练模型加载路径
# load_from = 'checkpoints/mask_rcnn_r50_fpn_1x_coco.pth'
load_from = 'checkpoints/epoch_12.pth'

# 8. 注册默认 scope
default_scope = 'mmdet'
